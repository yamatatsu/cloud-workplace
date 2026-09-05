# Cloud Workplace

VPS 上に「OpenCode の実行環境」と「LibreChat のホスティング」を構築するプロジェクト。

macbook を閉じていても、クラウド上の OpenCode がセッションを維持したままコーディングを継続でき、
スマホや PC から LibreChat チャットサービスにアクセスできる状態を目指す。

## 目的

1. **OpenCode 実行環境**
   - ローカル (macbook) を閉じていても、クラウド上でセッションを保持し、再接続してコーディングを継続できる。
2. **LibreChat ホスティング**
   - Claude Desktop ライクなチャットサービスを提供。
   - スマホ・PC からアクセス可能。

## インフラ

- **VPS**: シンVPS（契約済み・メモリ 2GB 以上）
- **セキュリティ**: Tailscale による閉域接続。Tailscale 以外の入口は塞ぐ。

## 利用技術

| 役割 | 技術 |
| --- | --- |
| モデル API | Fireworks API |
| 検索 API | Tavily API |
| モデル・ルーティング | Switchyard（OpenCode 専用） |
| チャットサービス | LibreChat（Fireworks へ直結） |
| コーディングハーネス | OpenCode |
| セッション管理 | Herdr（tmux 代替・agent-aware） |
| 閉域ネットワーク | Tailscale |

## アーキテクチャ

```
[macbook] ─ssh(tailscale)─┐        [スマホ / PC]
                          │              │
                      Tailscale (tailnet 内のみ)
                          │              │
                   ┌──────┴──────────────┴──────┐
                   │     VPS (シンVPS 2GB+)      │
                   │                            │
                   │  herdr ── OpenCode ──→ Switchyard ──→ Fireworks
                   │                                            └──→ Tavily
                   │  docker ─ LibreChat ──→ Fireworks
                   │            └ Mongo / Redis
                   └────────────────────────────┘
                     ↑ コードの真実の源は git リモート
```

## 設計方針

- **OpenCode の運用**: Herdr でセッションを常駐させ、Tailscale 経由の SSH（`herdr --remote`）で再接続する方式。人は都度プロンプトを投げる（自律エージェント的な継続はスコープ外）。
- **コードの真実の源**: git リモート（GitHub 等）を中心に、macbook / VPS 双方が clone & push する。
- **LibreChat のモデル接続**: Fireworks へ直結。Switchyard は OpenCode 専用とし、ルーティングを混在させない。
- **VPS リソース**: メモリ 2GB 以上。LibreChat + MongoDB(+Redis) の Docker 構成を前提。

## セキュリティ方針

- 具体的なセットアップ手順は [docs/spec/vps-security.md](docs/spec/vps-security.md) に定める。
- 通信は Tailscale の tailnet 内のみに限定。
- ファイアウォール（ufw 等）で Tailscale インターフェース以外の入力を全て遮断。SSH も Tailscale 経由のみ許可。
- Tailscale の Funnel / Firewall など外部公開機能は使わない。
- herdr のバックグラウンド更新チェック（phoning home）は config で無効化する。

## シークレット管理

シークレットは `.env`（gitignore 対象）に集約し、Docker Compose の `env_file` でコンテナへ渡す。OpenCode / herdr が参照するものは同 `.env` をシェルへ読み込む。

- `FIREWORKS_API_KEY`
- `SWITCHYARD_*`（Switchyard 用の設定/キー）
- `TAVILY_API_KEY`
- LibreChat の JWT 秘密鍵 (`CREDS_KEY` / `CREDS_IV` 等)

## HTTPS 接続

`tailscale serve` で `*.ts.net` の自動 HTTPS 証明書を使用して LibreChat を提供する。外部公開（Funnel / パブリック DNS）は行わない。

## 設計判断の記録

アーキテクチャ上の決定は [docs/ADR](docs/ADR/README.md) に記録している。

## 残課題・懸念

- [ ] Fireworks のモデル/機能対応確認（LibreChat でツール呼び出し等を使う場合、`dropParams` の必要性と対応モデルの選定）
- [ ] MongoDB をはじめとする各種データの耐久性（バックアップ等）…個人利用のため要求度は低く、優先度を下げて追跡
