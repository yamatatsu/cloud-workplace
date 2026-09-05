# ADR 0001: Docker Compose による展開

- Status: 決定
- Date: 2026-09-05

## Context

VPS 上に LibreChat（+ MongoDB）と OpenCode 実行環境を展開する。展開方式の選択が必要。

候補:

1. Docker Compose で LibreChat 群をコンテナ化する。
2. ベアメタルに直接インストール（apt/npm/バイナリ）。
3. k8s 等のオーケストレータを使う。

## Decision

LibreChat およびその依存（MongoDB）は Docker Compose でコンテナ化して展開する。OpenCode と herdr はコンテナではなく VPS 上のプロセスとして実行する（シェル/ファイルシステムを直接扱うため）。

## Consequences

- プラス: LibreChat の公式 compose 構成を流用でき、依存サービスを再現可能に立ち上げられる。
- プラス: 構成が `docker-compose.yml` + `librechat.yaml` + `.env` に集約され、管理しやすい。
- プラス: OpenCode は VPS のファイルシステムを直接触るため、コンテナ分離の複雑さを避けられる。
- マイナス: メモリ 2GB 程度では MongoDB のチューニングが必要になる可能性がある（残課題として追跡）。
