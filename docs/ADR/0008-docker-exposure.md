# ADR 0008: Docker コンテナの公開面を禁止（バインド制限 + DOCKER-USER）

- Status: 決定
- Date: 2026-09-05

## Context

LibreChat 等を Docker Compose で稼働させる際、Docker は iptables を直接操作するため、`-p 8080:8080` のような公開が UFW をバイパスして 0.0.0.0 に晒される。「Tailscale 以外の入口を塞ぐ」（ADR 0000）を Docker 導入後も維持するには、追加の対策が必要。

## Decision

コンテナのポートは公開 IP（0.0.0.0）にバインドしない。具体的には以下を恒久ルールとする。

1. コンテナポートは `127.0.0.1` または Tailscale IP にバインドする。
2. `DOCKER-USER` チェーンで tailscale0・ループバック・docker ブリッジ以外のインターフェースからの到達を遮断する（`iptables -I DOCKER-USER -i ! tailscale0 -j DROP`）。
3. 上記 iptables ルールは再起動で消えるため、永続化する（netfilter-persistent / UFW の before.rules）。

## Consequences

- プラス: Docker の UFW バイパスに左右されず、閉域方針がコンテナにも適用される。
- プラス: バインド先を誤って 0.0.0.0 にしても、DOCKER-USER が最終防御として働く。
- マイナス: iptables の永続化と、コンテナ追加時の一貫した守り方を運用規約として守る必要がある。
- マイナス: `tailscale serve` で外部から届ける場合、tailscale 経由のリクエストが DOCKER-USER を通過できるよう、ルールの順序（tailscale0 を許可側に含める）に注意が必要。
