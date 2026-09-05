# ADR 0007: SSH アクセスは Tailscale SSH を採用

- Status: 決定
- Date: 2026-09-05

## Context

VPS への管理用 SSH アクセス方式を決める必要がある。前提として、公開 IP に SSH ポートを晒さず、閉域でのみアクセスしたい（ADR 0000）。Web コンソール（noVNC）は存在するがペースト等の操作が不便なため、SSH 経由の復旧経路を別途確保しておくことが望ましい。

候補:

1. Tailscale SSH（tailnet の組み込み SSH 機能）
2. OpenSSH + 鍵認証（tailscale 経由、UFW で tailscale0 のみ許可）

## Decision

Tailscale SSH を主経路として採用する。認証・認可を tailnet の ACL に一元化し、公開インターフェースに OpenSSH の 22 番を立てない。ブートストラップ時のみ、Tailscale SSH の動作確認が取れるまで OpenSSH を fallback として残し、確認後に停止する（詳細は docs/spec/vps-security.md）。

## Consequences

- プラス: 公開面に SSH ポートが存在せず、パスワード総当たりやスキャンの対象にならない。
- プラス: root ログイン禁止・鍵管理を仕組みとして持たず、tailnet ACL で一元管理できる。
- プラス: OpenSSH の設定ミスによる公開露出リスクが低い。
- マイナス: Tailscale SSH は `tailscale ssh` 前提のため、標準 `ssh` を使うツール（herdr の `--remote` など）には `tailscale configure ssh` 相当の ProxyCommand 整備が必要（ADR 0003 と関係）。
- マイナス: Tailscale サービスが落ちると SSH 復旧経路を失う。noVNC コンソールが最終手段として残るが、複数デバイスにも SSH 復旧経路を確保するのが望ましい。
