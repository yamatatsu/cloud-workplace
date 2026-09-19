# ADR 0010: VPS を Oracle Cloud（Always Free / Ampere A1）に移行

- Status: 決定
- Date: 2026-09-12

## Context

これまでの VPS（シンVPS, x86 Ubuntu）を、Oracle Cloud Infrastructure（OCI）の Always Free 枠に移行したい。目的はコスト削減とスペック向上（2 OCPU / 12GB が無料枠内で使える）。

前提となるセキュリティ要件は変わらない: アクセス経路は **OCI コンソールのシリアルコンソール接続と Tailscale のみ**とし、それ以外の入口は全て遮断する（ADR 0000, 0007）。

候補:

1. OCI Always Free の Ampere A1（`VM.Standard.A1.Flex`, ARM aarch64）に移行する。
2. OCI Always Free の AMD Micro（`VM.Standard.E2.1.Micro`, 1/8 OCPU / 1GB）に移行する。
3. シンVPS を使い続ける。

## Decision

候補 1 を採用し、VPS を OCI Always Free の Ampere A1（2 OCPU / 12GB、Ubuntu 24.04 aarch64）に移行する。AMD Micro はスペック不足のため不採用。

ネットワークは、セキュリティリストの ingress ルールを**ゼロ**（全拒否）とし、OS 側も UFW で tailscale0 以外の入力を deny する二重構成とする。SSH は引き続き Tailscale SSH のみとし、OpenSSH はブートストラップ後に停止する。ロックアウト時の最終手段は、シンVPS の noVNC に相当するものとして OCI の**シリアルコンソール接続（Console Connection）**を使用する。

あるべき姿と到達手順の詳細は docs/spec/vps-security.md、移行作業計画は docs/plans/001-oracle-cloud-migration.md を参照。

## Consequences

- プラス: 常時無料枠内で 2 OCPU / 12GB が使え、シンVPS より高スペックをコストゼロで運用できる。
- プラス: OCI のセキュリティリスト（L3/L4）で ingress 全拒否にでき、OS 設定ミスがあってもインターネット側で遮断される多層防御になる。
- プラス: シリアルコンソール接続は sshd/Tailscale 非依存で、noVNC と同等以上の復旧経路になる。
- マイナス: **ARM（aarch64）アーキテクチャ**になるため、Docker イメージやツールが arm64 対応している必要がある（LibreChat / MongoDB 等のイメージ対応は移行計画で検証）。
- マイナス: Always Free の Ampere A1 はリージョン/AD によって容量不足で作成できない場合がある。また無料枠の仕様（現在: 合計 2 OCPU / 12GB）は Oracle 側のポリシー変更に左右される。
- マイナス: 公開 IP はエフェメラルのため再起動等で変わりうる（運用上は Tailscale 経由のみのため影響は小さい）。
- マイナス: 移行に伴い tailnet 上のホスト名・IP が変わるため、クライアント側の設定（ProxyCommand、MagicDNS 名）と LibreChat 等のデータ移行が必要。
