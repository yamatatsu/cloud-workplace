# ADR 0004: LibreChat は Fireworks 直結、Switchyard は OpenCode 専用

- Status: 決定
- Date: 2026-09-05

## Context

モデル API（Fireworks）への接続経路として、ルーティング用の Switchyard をどこに挟むかが論点。

候補:

1. LibreChat は Fireworks へ直結し、Switchyard は OpenCode 専用とする。
2. LibreChat も Switchyard 経由にし、ルーティングを一元化する。

## Decision

LibreChat は Fireworks の OpenAI 互換 API へ直結する。Switchyard は OpenCode 専用とし、会話系サービスには挟まない。

## Consequences

- プラス: LibreChat は公式の Fireworks カスタムエンドポイント構成でシンプルに動かせる。
- プラス: チャットとコーディングでルーティング方針を分離でき、切り分けが明快。
- マイナス: ルーティング設定を Switchyard に集約できないため、LibreChat 側はモデル選定を静的構成で行う。
- 注意: Fireworks はモデルによって `user` 等のフィールドを reject するため、LibreChat 側で `dropParams` の設定が必要になる場合がある。
