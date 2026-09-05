# ADR 0005: シークレット管理は .env + env_file

- Status: 決定
- Date: 2026-09-05

## Context

VPS 上で Fireworks / Switchyard / Tavily / LibreChat（JWT 鍵）等のシークレットを管理する必要がある。
現状の `mise.local.toml` は macOS Keychain 前提のため VPS では使えない。

候補:

1. `.env`（gitignore 対象）+ Docker Compose の `env_file` で管理する。
2. Docker secrets を使う。
3. age / sops で暗号化してリポジトリにコミットする。

## Decision

シークレットは `.env`（gitignore 対象）に集約し、Docker Compose の `env_file` でコンテナへ渡す。OpenCode / herdr が参照するものは同 `.env` をシェルへ読み込む。

## Consequences

- プラス: 構成が単純で、LibreChat 標準の `.env` 運用と相性が良い。
- プラス: git リポジトリに秘密情報が混入しない（`.gitignore` で確実に除外する）。
- マイナス: 暗号化せず平文で VPS のディスクに置くため、VPS の root 漏えい時は露出する。
- マイナス: 複数環境やバックアップで秘密を扱う場合は、別途の暗号化を検討する余地がある（個人利用のため現時点では許容）。
