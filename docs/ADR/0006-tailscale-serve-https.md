# ADR 0006: HTTPS は Tailscale の仕組み（tailscale serve）で提供

- Status: 決定
- Date: 2026-09-05

## Context

スマホ/PC のブラウザから LibreChat へアクセスする際、平文 HTTP だとログイン時にブラウザ警告が生じるため、HTTPS での提供が望ましい。ただし外部公開はしない方針。

候補:

1. `tailscale serve` で `*.ts.net` の自動 HTTPS 証明書を使う。
2. 自前リバースプロキシ（Caddy 等）で証明書を発行する。
3. 平文 HTTP のまま運用する。

## Decision

`tailscale serve` を用い、tailnet 内で `*.ts.net` の HTTPS 証明書により LibreChat を提供する。外部公開（Funnel / パブリック DNS）は行わない。

## Consequences

- プラス: 証明書管理を Tailscale に任せられ、公開 DNS を立てずに HTTPS が手に入る。
- プラス: アクセス元は tailnet 内に限定されたままで、警告のないブラウザ体験が得られる。
- マイナス: Tailscale の serve 機能に依存するため、MagicDNS / HTTPS 証明書機能の有効化が必要。
- マイナス: カスタムドメイン（`*.ts.net` 以外）を使う場合の柔軟性は限られる。
