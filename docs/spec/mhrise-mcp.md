# MHRise MCP サーバー（DuckDB + FastMCP）

LibreChat からモンスターハンターライズ（サンブレイク含む）のゲームデータを自然言語で検索するための仕様。決定の経緯は ADR 0012 を参照。

## 決定事項

| 項目             | 決定                                                            |
| ---------------- | --------------------------------------------------------------- |
| データソース     | MHRice（`https://mhrise.mhrice.info/mhrice.json`、2024-02 版）  |
| データ保持       | 全 246 キーをロスレス保持。カテゴリ別 7 ファイルに分割し gzip でコミット（計約 12MB） |
| 検索エンジン     | DuckDB（read-only）                                             |
| 公開 I/F         | MCP（streamable-http）。FastMCP 製の自作サーバー                |
| 展開             | docker-compose の `mhrise-mcp` サービス（ポートはホスト非公開） |
| LibreChat 側設定 | `mcpServers` + `mcpSettings.allowedAddresses`                   |

## ファイル構成

```
librechat/
├── librechat.yaml              # mcpServers / mcpSettings を追加
└── mhrise/
    ├── data/                   # コミット対象（ETL の生成物・計約 12MB）
    │   ├── weapons.json.gz     #   武器 14 種・派生ツリー・百竜武器スキル（約 3.2MB）
    │   ├── monsters.json.gz    #   モンスター肉質・状態異常耐性など（約 1.2MB）
    │   ├── armor_skills.json.gz#   防具・スキル・装飾品（約 1.6MB）
    │   ├── items.json.gz       #   アイテム・素材・調合（約 1.4MB）
    │   ├── quests.json.gz      #   クエスト・報酬（約 1.9MB）
    │   ├── otomo.json.gz       #   オトモ装備（約 1.0MB）
    │   └── misc.json.gz        #   マップ・環境生物・勲章など残り（約 1.5MB）
    ├── etl/
    │   └── build_data.py       # mhrice.json を DL → カテゴリ分割 → gzip 出力
    └── mcp/
        ├── Dockerfile          # python:3.12-slim + duckdb + fastmcp
        └── server.py           # 起動時に data/ をビュー登録し MCP ツールを公開
```

## データ生成（ETL）

```bash
python3 librechat/mhrise/etl/build_data.py
```

- MHRice の JSON をダウンロード（キャッシュ: `/tmp/mhrice.json`）し、カテゴリ別に分割して `data/*.json.gz` に出力する
- 依存は標準ライブラリのみ
- MHRice は 2024-02 で更新停止（ゲーム最終版）のため、再実行は原則不要

## MCP サーバー

### 起動時の処理

1. `/data/*.json.gz` を読み込み、各キーを DuckDB（in-memory）のテーブルとしてロードする
   - `{"param"/"entries"/"data_list": [...]}` はリスト要素を 1 行ずつ展開
   - サブグループの入れ物（例: `great_sword = {base_data, name, tree, ...}`）は `<キー>__<サブキー>` に再帰分割（例: `great_sword__base_data`）
   - 全 441 テーブル
2. MCP サーバーとして `0.0.0.0:8000`（streamable-http、パス `/mcp`）で待受

### 公開ツール

| ツール            | 説明                                                        |
| ----------------- | ----------------------------------------------------------- |
| `query`           | DuckDB SQL を実行（read-only）。行数・文字数に上限あり      |
| `list_tables`     | テーブル一覧を返す                                          |
| `describe_table`  | 指定テーブルのカラム定義を返す                              |

### データ構造上の注意（MCP instructions にも記載）

- 名称・説明文のテーブル（`*__name` / `*_msg` 系）は `content` カラムが 32 言語の配列。DuckDB は 1-indexed で `content[1]` = 日本語、`content[2]` = 英語
- 武器テーブル（`great_sword__base_data` 等）はネストした struct 構造。struct のフィールドアクセスはブラケット記法（例: `base['base']['base']['atk']`）を使う。深さは武器種で異なるため `describe_table` で確認してからクエリすること
- 武器名は `<武器種>__name`（無印分）と `<武器種>__name_mr`（MR 分）に分割されており、`base_data` は無印→MR の順に並ぶ。`name` の後ろに `name_mr` を連結すると行の並びが対応する（`row_number()` で JOIN）
- サンブレイク（MR）追加分は `*_mr` サフィックスのテーブルに入っている
- 「クリア後テスト用」「TU3テスト用」などのテスト用データも含まれる（回答時は除外を指示済み）

## docker-compose への追加

```yaml
mhrise-mcp:
  build: ./librechat/mhrise/mcp
  container_name: mhrise-mcp
  restart: always
  volumes:
    - ./librechat/mhrise/data:/data:ro
```

- ポートは公開しない（ADR 0008）。LibreChat コンテナから docker ネットワーク経由でのみ到達

## librechat.yaml への追加

```yaml
mcpServers:
  mhrise:
    type: streamable-http
    url: http://mhrise-mcp:8000/mcp
    requiresOAuth: false
    timeout: 60000
    serverInstructions: true

mcpSettings:
  allowedAddresses:
    - "mhrise-mcp:8000"
```

- `allowedAddresses`: LibreChat の SSRF 保護はプライベートアドレスへの MCP 接続を既定でブロックするため、host:port 形式での明示許可が必須
- yaml 変更後は LibreChat の再起動が必要（初期化は起動時）

## 使い方

- 通常チャット: ツール対応モデルを選択し、入力欄下のツールドロップダウンから `mhrise` を選択
- エージェント: Agent Builder の Add tools → MCP から `mhrise` を選択して保存

## 残課題・確認事項

- [ ] 現行モデル（Fireworks 経由 deepseek-v4p1-flash）が tool calling に対応しているか実機確認
- [ ] VPS（メモリ 2GB 程度）での DuckDB / MCP コンテナの実メモリ使用量を計測
- [ ] `*_msg` テーブルの 32 言語配列は冗長なので、必要になれば ETL で日英のみに平坦化する
- [ ] リポジトリを public にする場合は `data/`（ゲームデータ抽出物・著作権はカプコン）の取り扱いを再検討
