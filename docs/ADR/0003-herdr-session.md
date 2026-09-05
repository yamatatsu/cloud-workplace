# ADR 0003: OpenCode セッション管理に herdr を採用

- Status: 決定
- Date: 2026-09-05

## Context

「macbook を閉じても OpenCode がコーディングを継続できる」状態を作るには、VPS 上でセッションを常駐させ、
クライアントから再接続できる仕組みが必要。

候補:

1. herdr（agent-aware なターミナルランタイム）
2. tmux
3. zellij
4. systemd ユニットでバックグラウンド実行

## Decision

herdr を採用する。OpenCode を VPS 上の herdr セッションで常駐させ、Tailscale 経由の SSH（`herdr --remote`）で detach / reattach する。人は都度プロンプトを投げる（自律エージェント的な継続はスコープ外）。

あわせて herdr のバックグラウンド更新チェック（phoning home）は config で無効化する。

## Consequences

- プラス: agent の状態（blocked / working / done / idle）を把握でき、OpenCode との直接統合がある。
- プラス: バックグラウンドサーバとして稼働するため、SSH が切れてもセッションは維持される。
- マイナス: tmux に比べ若いプロジェクトで、API/プラグイン面は発展途上。
- マイナス: デフォルトで外部へ通信する（更新チェック）ため、off にする設定が必須。
