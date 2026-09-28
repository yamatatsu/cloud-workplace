# ADR 0012: モンスターハンターライズのゲームデータ検索を DuckDB + MCP サーバーで提供する

- Status: 決定
- Date: 2026-09-28

## Context

LibreChat からモンスターハンターライズ（サンブレイク含む）の武器データを自然言語で調べられるようにしたい。今後は武器以外（モンスター・防具・スキル・クエスト等）のデータも対象にしたい。

検討した論点は以下の 3 点。

### 1. データソース

候補:

1. **MHRice**（<https://mhrise.mhrice.info/>）— ゲームファイルから直接抽出したデータを `mhrice.json`（約 124MB）としてダウンロード提供。全 14 武器種・モンスター・防具・クエスト等を網羅し、サンブレイク最終版（2024-02 ビルド）まで含む。名称は日本語を含む多言語
2. Badge87/MHRiseScraperData（GitHub のスクレイプ JSON）— 2022-01 時点で無印ライズのみ、英語名
3. mh-api.com（公開 REST API）— 無料・認証不要だが、実際に叩くと収録は Wilds のデータでライズは対象外
4. docs.mhw-db.com 等 — World のみ

### 2. データの保持方法

候補:

1. **全データをリポジトリにコミット**（スリム化なし）
2. 武器など必要な部分だけ抽出したスリム版をコミット
3. データはコミットせず、起動時に外部からダウンロード

### 3. 検索インターフェース

候補:

1. **DuckDB + 自作 MCP サーバー**（streamable-http）— LLM が SQL を書いて柔軟に検索できる
2. RAG API / Vector DB（ADR 0009 で不採用）— 「攻撃力◯以上の大剣」のような構造化クエリに不向き
3. Actions（OpenAPI スキーマの HTTP API）— 固定 API では柔軟な検索が難しい
4. LibreChat Code Interpreter — 有料の外部サービス。ADR 0009 の最小構成方針に反する

## Decision

### データソース: MHRice を採用

- ゲームファイル由来で正確・最新（サンブレイク最終版まで網羅）
- 自前ホストのため API の死活・レート制限に左右されない
- 日本語名がそのまま入っている

### データ保持: 全データをカテゴリ分割 + gzip 圧縮してコミット

- MHRice の JSON は全 246 キー（武器 14 種・モンスター・防具・スキル・クエスト・アイテム・オトモ・その他）を含み、**全カテゴリをロスレスで保持**する。将来の対象拡大で ETL のやり直しを不要にするため
- そのまま 1 ファイル（124MB）だと GitHub の 100MB/ファイル制限に抵触するため、**カテゴリ別 7 ファイルに分割**する
- **gzip 圧縮（`.json.gz`）でコミット**。実測で raw 67MB → gzip 計約 12MB となり、Git LFS なしで通常コミット可能。DuckDB は `.json.gz` を伸張なしで直接読める
- 更新は `etl/build_data.py` を実行して `data/` を再生成する（MHRice は 2024-02 で更新停止＝ゲーム最終版のため、基本的に一度きり）

### 検索 I/F: DuckDB を内蔵した自作 MCP サーバー（streamable-http）

- FastMCP（Python）で薄い MCP サーバーを自作し、docker-compose のサイドカーとして `mhrise-mcp` サービスを追加する
- 既存の DuckDB MCP 実装（mcp-server-duckdb / mcp-server-motherduck）は stdio 前提で、マルチコンテナ構成・マルチユーザーに向かない。LibreChat 公式も本番では streamable-http を推奨している
- DuckDB は read-only で開き、公開ツールは `query` / `list_tables` / `describe_table` に限定。結果は行数・文字数を制限してコンテキスト肥大化を防ぐ
- LibreChat 側は `librechat.yaml` の `mcpServers` に追加し、`mcpSettings.allowedAddresses` で内部アドレス（`mhrise-mcp:8000`）への接続を許可する（SSRF 保護の既定ブロックを回避するため必須）
- ポートはホストに公開しない（ADR 0008 に準拠。docker ネットワーク内部のみ）

### 著作権への配慮

MHRice のデータはゲームデータの抽出物であり、著作権はカプコンに帰属する。本リポジトリは個人利用（Tailscale 閉域・外部公開なし、ADR 0000 / 0006）の範囲で運用する。リポジトリを public にする場合は `data/` の取り扱いを再検討する。

## Consequences

- プラス: 「火属性で攻撃力 300 以上の大剣は？」のような柔軟な構造化クエリに自然言語で答えられる
- プラス: 全カテゴリのデータを保持するため、武器以外への対象拡大は MCP サーバーの instructions 更新だけで済む
- プラス: 追加の外部サービス・課金なし。既存の docker-compose に 1 コンテナ足すだけ
- プラス: リポジトリへの追加は約 12MB で済む
- マイナス: MCP ツール利用にはモデルの tool calling 対応が必須。現行モデル（Fireworks 経由 deepseek-v4p1-flash）の対応は実機確認が必要（docs/spec/librechat.md の残課題にも関連）
- マイナス: LibreChat 本体・MCP サーバー双方のコンテナが増え、VPS（メモリ 2GB 程度、ADR 0009）のリソースを圧迫する可能性がある。DuckDB のメモリ使用量はデータ規模（数十MB級）から見て小さいと見込むが、導入後に実測する
- マイナス: 著作権上の注意が発生する（上記）
