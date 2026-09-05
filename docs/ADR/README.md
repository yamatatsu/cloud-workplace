# Architecture Decision Records

このディレクトリには、Cloud Workplace プロジェクトのアーキテクチャ決定を記録する。

| # | ADR | 概要 | Status |
| --- | --- | --- | --- |
| 0000 | [tailscale-closed-network](0000-tailscale-closed-network.md) | Tailscale による閉域ネットワーク | 決定 |
| 0001 | [docker-compose-deployment](0001-docker-compose-deployment.md) | Docker Compose による展開 | 決定 |
| 0002 | [git-remote-source-of-truth](0002-git-remote-source-of-truth.md) | コードの真実の源を git リモートに統一 | 決定 |
| 0003 | [herdr-session](0003-herdr-session.md) | OpenCode セッション管理に herdr を採用 | 決定 |
| 0004 | [librechat-direct-fireworks](0004-librechat-direct-fireworks.md) | LibreChat は Fireworks 直結 / Switchyard は OpenCode 専用 | 決定 |
| 0005 | [secret-management](0005-secret-management.md) | シークレット管理は .env + env_file | 決定 |
| 0006 | [tailscale-serve-https](0006-tailscale-serve-https.md) | HTTPS は tailscale serve で提供 | 決定 |
| 0007 | [tailscale-ssh](0007-tailscale-ssh.md) | SSH アクセスは Tailscale SSH を採用 | 決定 |
| 0008 | [docker-exposure](0008-docker-exposure.md) | Docker コンテナの公開面を禁止 | 決定 |
