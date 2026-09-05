# ADR 0000: Tailscale による閉域ネットワーク

- Status: 決定
- Date: 2026-09-05

## Context

VPS 上に OpenCode 実行環境と LibreChat を構築する。スマホ・PC・macbook からアクセスする一方で、インターネットに公開せず安全に接続したい。

候補:

1. Tailscale で閉域化し、tailnet 内のみにアクセスを限定する。
2. インターネット公開 + 認証（パスワード/OAuth）で保護する。
3. Cloudflare Tunnel（Cloudflare Access）でアクセス制御する。

## Decision

Tailscale による閉域ネットワークを採用する。Tailscale 以外の入口はファイアウォール（ufw 等）で全て遮断し、SSH も Tailscale 経由のみ許可する。Tailscale Funnel / Firewall 等の外部公開機能は使用しない。

## Consequences

- プラス: 公開面が存在せず、IP/ポートスキャンや総当たり攻撃の対象にならない。認証基盤を Tailscale に委譲できる。
- プラス: クライアント（macbook / スマホ / PC）は Tailscale アプリを入れるだけで安全に接続できる。
- マイナス: クライアント側に Tailscale の導入・ログインが必須。デバイス追加時は tailnet への招待が必要。
- マイナス: tailnet のアカウント/デバイス管理が信頼境界になるため、その運用が重要。
