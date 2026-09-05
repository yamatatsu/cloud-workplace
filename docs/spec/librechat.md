# LibreChat 構成（Docker Compose）

LibreChat を Fireworks 直結・最小構成で Docker Compose 展開するための仕様と決定事項。

## 決定事項

| 項目         | 決定                                                    |
| ------------ | ------------------------------------------------------- |
| 展開方式     | Docker Compose（ADR 0001）                              |
| 依存サービス | MongoDB のみ（Redis / Meilisearch / RAG は不使用）      |
| モデル接続   | Fireworks 直結（ADR 0004）                              |
| モデル定義   | `fetch: true`（Fireworks のモデルを動的取得）           |
| 認証         | LibreChat 組み込み auth（メール/PW）。SMTP 不使用       |
| イメージ     | `ghcr.io/danny-avila/librechat:v0.8.4`（pin）           |
| ポート露出   | コンテナ 3080 を `127.0.0.1` にのみバインド（ADR 0008） |
| HTTPS / 公開 | `tailscale serve` で提供（ADR 0006。外部公開なし）      |
| シークレット | `.env` に集約（ADR 0005。gitignore 対象）               |

## 依存サービスの判断

LibreChat のオプション依存と、本構成での扱いは以下の通り。

| サービス            | 用途                                      | 本構成 | 理由                                                                             |
| ------------------- | ----------------------------------------- | ------ | -------------------------------------------------------------------------------- |
| MongoDB             | 必須のデータストア                        | 使用   | 本体の必須依存                                                                   |
| Redis               | キャッシュ / セッション（水平スケール用） | 不使用 | 単一インスタンスでは in-memory で十分（公式でも experimental / overkill と明記） |
| Meilisearch         | 会話履歴の全文検索（`SEARCH=true`）       | 不使用 | 検索機能を有効にしたくなったら導入を再検討                                       |
| RAG API / Vector DB | アップロード文書の検索・質問応答          | 不使用 | 2GB に収めるため。full stack は 2GB/2vCPU 推奨で余裕がない                       |

## ファイル構成

`docker-compose.yml` はリポジトリのトップレベルに置く（今後の構成追加をトップレベル 1 本に集約する方針）。LibreChat 関連のファイルは `librechat/` に閉じる。

```
docker-compose.yml         # LibreChat + MongoDB（トップレベル）
.env                       # シークレット（gitignore・手動作成）
librechat/
└── librechat.yaml          # Fireworks エンドポイント定義
```

## シークレット（`.env`）

以下を生成して `.env` に記載する（いずれも再起動後も同一値を維持する必要あり）。

| キー                | 生成                   | 備考                         |
| ------------------- | ---------------------- | ---------------------------- |
| `JWT_SECRET`        | `openssl rand -hex 32` | JWT 署名（アクセストークン） |
| `JWT_REFRESH_SECRET`| `openssl rand -hex 32` | JWT 署名（リフレッシュトークン） |
| `CREDS_KEY`         | `openssl rand -hex 32` | 認証情報の暗号化鍵（64文字） |
| `CREDS_IV`          | `openssl rand -hex 16` | 認証情報の IV（32文字）      |
| `FIREWORKS_API_KEY` | Fireworks コンソール   | モデル API                   |

`ADMIN_PANEL_SESSION_SECRET` は単体の admin panel を使う場合のみ必要で、本構成では不要。

## 認証運用

1. 初回起動時は `ALLOW_REGISTRATION=true` のまま起動し、ブラウザから最初のアカウントを登録（これが管理者になる）。
2. 管理者アカウント確定後は `ALLOW_REGISTRATION=false` に変更して再起動し、新規登録を閉じる。

## 公開経路

1. LibreChat は `127.0.0.1:3080` にのみバインド（Docker の公開 IP 露出なし）。
2. `tailscale serve` で `<host>.ts.net` の HTTPS 証明書を付与して提供する（詳細は ADR 0006）。
3. 外部公開（Funnel / パブリック DNS）は行わない。

```bash
tailscale serve --bg --https=443 http://127.0.0.1:3080
```

## モデル定義

`librechat.yaml` で Fireworks を custom endpoint として定義する。`fetch: true` により Fireworks のモデル一覧を動的に取得するため、`default` に 1 本だけモデルを指定する。

- `baseURL`: `https://api.fireworks.ai/inference/v1`
- `dropParams`: `["user"]`（Fireworks が `user` フィールドを reject するため。ADR 0004）
- `default` / `titleModel`: 承継利用可能なモデルを 1 本指定。Fireworks のモデルカタログは頻繁に変わるため、導入時に実在するモデル ID を確認して設定する。

## 残課題・確認事項

- [ ] Fireworks のデフォルト/タイトル用モデル ID を、導入時点のカタログと照合して確定する
- [ ] MongoDB のデータ永続性・バックアップ（優先度低として追跡）
- [ ] ツール呼び出し等を使う場合の対応モデル / `dropParams` の要否（ADR 0004 注意事項）
