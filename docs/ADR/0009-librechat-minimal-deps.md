# ADR 0009: LibreChat は最小構成（MongoDB のみ）で展開する

- Status: 決定
- Date: 2026-09-05

## Context

LibreChat の依存サービス選定が論点。公式の Docker 構成は MongoDB に加え、Meilisearch（会話履歴の全文検索）、Redis（キャッシュ / セッション）、RAG API / Vector DB（文書検索）を任意で含む。一方、VPS はメモリ 2GB 程度（ADR 0001 の残課題）であり、公式の full stack は 2GB / 2vCPU 推奨で余裕がない。

候補:

1. MongoDB のみの最小構成
2. MongoDB + Meilisearch（検索あり）
3. 公式どおりの full stack（+ RAG / Vector DB）

## Decision

MongoDB のみの最小構成とする。あわせて以下を決定する。

- **Redis**: 使わない。単一インスタンスでは in-memory で十分（公式でも experimental / overkill と明記）。
- **Meilisearch（`SEARCH`）**: 今回無効。会話履歴の全文検索が必要になったら再検討する。
- **RAG API / Vector DB**: 使わない。
- **モデル定義**: `librechat.yaml` で `fetch: true` による動的取得とする（ADR 0004 の「静的選定」記述を本 ADR で更新する）。Fireworks のモデルカタログは頻繁に変わるため、動的取得の方が追従しやすい。
- **認証**: LibreChat 組み込み auth（メール / PW）とし、SMTP は使わない。初回起動で最初のユーザーを登録（管理者）し、その後 `ALLOW_REGISTRATION=false` に変更して新規登録を閉じる。
- **イメージ**: `ghcr.io/danny-avila/librechat:v0.8.4` に pin する。

## Consequences

- プラス: 2GB の VPS に収まり、メモリ不足の懸念を解消できる。
- プラス: 構成がシンプルで起動・管理が容易。
- プラス: `fetch: true` により Fireworks のモデル追加 / 廃止に追従でき、デフォルトのモデル ID を 1 本だけ保守すればよい。
- マイナス: 会話履歴の全文検索・文書 RAG は使えない（必要になったら Meilisearch / RAG を追加）。
- マイナス: 初期管理者の手動登録と、その後の `ALLOW_REGISTRATION` の手動変更という運用が発生する。
