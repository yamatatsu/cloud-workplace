# AGENTS.md

このリポジトリで作業するエージェント向けの前提知識。詳細は `README.md` および `docs/` を参照。

## プロジェクト概要

VPS 上に以下を構築・運用するプロジェクト。

1. **OpenCode 実行環境**: Herdr でセッション常駐。Tailscale 経由の SSH（`herdr --remote`）で再接続してコーディングを継続する。
2. **LibreChat ホスティング**: スマホ・PC からアクセス可能なチャットサービス。モンハンライズのデータ検索用 MCP サーバー付き。

コードの真実の源は git リモート（GitHub）。macbook / VPS の双方で clone & push する。

## リポジトリ構成

```
cloud-workplace/
├── docker-compose.yml      # LibreChat + MongoDB + mhrise-mcp
├── .env.example            # シークレットの雛形（.env は gitignore）
├── opencode.json           # OpenCode のパーミッション設定
├── mise.local.toml         # ツールバージョン管理（mise）
├── setup-vps/
│   └── init.sh             # VPS 初期セットアップ手順（zsh / Docker 等）
├── librechat/
│   ├── librechat.yaml      # LibreChat 設定（エンドポイント / MCP / Web 検索）
│   └── mhrise/             # MHRise MCP サーバー関連
│       ├── data/           # ETL 生成物（*.json.gz、コミット対象）
│       ├── etl/build_data.py  # データ生成スクリプト（uv 前提）
│       └── mcp/            # FastMCP サーバー（Dockerfile 同梱）
├── infra/terraform/        # OCI リソース定義（Terraform）
└── docs/
    ├── ADR/                # アーキテクチャ決定記録（0000〜0012）
    ├── plans/              # 移行計画書
    └── spec/               # 仕様書（vps-security / librechat / mhrise-mcp）
```

## インフラ・環境

- **クラウド**: Oracle Cloud Infrastructure（Always Free 枠）
  - インスタンス: `VM.Standard.A1.Flex`（Ampere A1、ARM aarch64）、2 OCPU / 12GB
  - OS: Canonical Ubuntu 24.04 Minimal（aarch64）
- **IaC**: Terraform（`infra/terraform/`、oci provider）。`terraform.tfvars` に tenancy 等の OCID を設定。
- **ネットワーク**: Tailscale による閉域接続（tailnet 内のみ）。
  - OCI セキュリティリストの ingress はゼロ。egress は全許可。
  - UFW: incoming 既定 deny、`tailscale0` のみ入力許可。
  - SSH は Tailscale SSH のみ。OpenSSH（sshd）は停止・無効化。
  - Tailscale Funnel など外部公開機能は使わない。
- **ロックアウト時の最終手段**: OCI コンソールのシリアルコンソール接続。
- **詳細手順**: `docs/spec/vps-security.md`。VPS 変更時は「旧経路が使えることを確認してから閉じる」を徹底。

## サービス構成（docker-compose.yml）

| サービス | イメージ / ビルド | 役割 |
| --- | --- | --- |
| `librechat` | `ghcr.io/danny-avila/librechat:v0.8.7`（pin） | チャット本体。`./.env` と `./librechat/librechat.yaml` を read-only マウント |
| `mongodb` | `mongo:8.0.20`（`mongod --noauth`） | LibreChat のデータストア（必須依存） |
| `mhrise-mcp` | `./librechat/mhrise/mcp` からビルド | MHRise データ検索用 MCP サーバー。`./librechat/mhrise/data` を read-only マウント |

- ボリューム: `librechat-data`、`mongodb-data`
- Redis / Meilisearch / RAG は不使用（最小構成。ADR 0009）
- Docker コンテナは公開 IP にバインドしない（`127.0.0.1` / Tailscale IP のみ。ADR 0008）

## 利用技術とルーティング

| 役割 | 技術 | 備考 |
| --- | --- | --- |
| モデル API | Fireworks API | LibreChat / OpenCode 共通 |
| 検索 API | Tavily API | LibreChat の Web 検索（searchProvider / scraperProvider ともに tavily） |
| モデル・ルーティング | Switchyard | OpenCode 専用。LibreChat は Fireworks 直結で混在させない（ADR 0004） |
| コーディングハーネス | OpenCode | 設定は `opencode.json` |
| セッション管理 | Herdr | tmux 代替。phoning home は config で無効化する |

## LibreChat 設定（librechat/librechat.yaml）

- カスタムエンドポイント `Fireworks`（`https://api.fireworks.ai/inference/v1`）
  - ヘッダ `x-routing-preference: "4"`（1=品質最優先〜5=コスト最優先）
  - `fetch: true` でモデルを動的取得
  - タイトル生成・要約は `accounts/fireworks/models/deepseek-v4p1-flash`（日本語タイトル）
  - `dropParams: ["user"]`
- Web 検索は Tavily（`${TAVILY_API_KEY}` を環境変数参照）
- MCP サーバー `mhrise` を streamable-http で接続（`http://mhrise-mcp:8000/mcp`）
  - `mcpSettings.allowedAddresses` に `mhrise-mcp:8000` を指定済み

## MHRise MCP サーバー

- データソース: MHRice（`https://mhrise.mhrice.info/mhrice.json`、2024-02 版）
- ETL: `librechat/mhrise/etl/build_data.py` がカテゴリ別 7 ファイル（*.json.gz、計約 12MB）を `librechat/mhrise/data/` に生成。**生成物はコミット対象**
- サーバー: FastMCP 製（`librechat/mhrise/mcp/server.py`）
  - 起動時に *.json.gz を DuckDB（in-memory、read-only）にロードし、派生ビューを作成
  - **武器検索は `v_<武器種>` ビューが入口**（名称結合・atk/rare/属性等の平坦化済み。`v_horn` は旋律名列あり）。他に `v_horn_melody` / `v_hyakuryu_skill`
  - streamable-http で公開。ホスト側ポートは公開しない
  - 実行可能なのは読み取り系ステートメントのみ（select / with / explain / describe / show）
  - 生テーブルはネストした struct を含む。struct フィールドアクセスはブラケット記法（`col['x']['y']`）
  - 武器名と base_data の結合キーは名称テーブルの `name` 列（`W_<武器種>_<id>_Name` 形式）に含まれる武器 id。行の並びは武器種により一致しない
  - `content` カラムは 32 言語配列。DuckDB は 1-indexed（`content[1]`=日本語）
- 詳細: `docs/spec/mhrise-mcp.md`

## シークレット管理

- シークレットは `.env`（gitignore 対象）に集約。`.env.example` が雛形（ADR 0005）
- Docker Compose は `./.env` をコンテナへ read-only マウント
- 主なキー: `JWT_SECRET` / `JWT_REFRESH_SECRET` / `CREDS_KEY` / `CREDS_IV` / `FIREWORKS_API_KEY` / `TAVILY_API_KEY` / `ALLOW_REGISTRATION`
- 初回起動時は `ALLOW_REGISTRATION=true` で管理者登録後、`false` に変更して再起動
- `.env` や tfstate・キー類をコミットしないこと

## 開発・運用コマンド

```bash
# サービス起動 / 停止（VPS 上）
docker compose up -d
docker compose down
docker compose logs -f librechat

# MHRise データの再生成
cd librechat/mhrise/etl && uv run build_data.py

# Terraform（infra/terraform/）
terraform plan -out=tfplan
terraform apply tfplan
```

## ドキュメント規約

- **ADR**（`docs/ADR/`）: アーキテクチャ上の決定を記録。新たな設計判断をしたら番号を付けて追加し、`docs/ADR/README.md` の一覧を更新する
- **spec**（`docs/spec/`）: 現在あるべき姿・構成の仕様
- **plans**（`docs/plans/`）: 移行・セットアップの計画書
- ドキュメントは日本語で書く

## 注意事項

- 設計方針に反する変更（例: LibreChat に Switchyard を噛ませる、Tailscale 以外の入口を開ける、Redis 等を追加する）をする場合は ADR を確認し、必要なら新規 ADR を起票する
- Terraform の state（`infra/terraform/terraform.tfstate`）はリポジトリ内で管理されている。apply 後にコミット対象になる
- VPS 上の変更は git リモートを経由して同期する（VPS で直接編集したままにしない）
