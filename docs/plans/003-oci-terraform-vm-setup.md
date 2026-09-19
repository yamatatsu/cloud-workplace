# Terraform で OCI に VM を起動する手順（要件）

- 関連: ADR 0010（OCI への移行）、ADR 0011（Terraform 採用の決定）、docs/spec/vps-security.md（あるべき姿）
- 目的: Oracle 公式の OCI Terraform Provider（`oracle/oci`）で、コンパートメント → VCN → サブネット → インスタンス → シリアルコンソール接続までを宣言的に作成する
- 特徴: コンソール / CLI と違い**宣言的・再現可能**。不要な NAT / Service Gateway は作らない

本書は Terraform コードそのものではなく、**`infra/terraform/` に用意する Terraform 構成が満たすべき要件**を定義する。実装は本書の要件に従うこと。

## 前提

- Terraform 1.3 以上をインストール済み
- OCI の API キー認証が設定済み（`oci setup config` により `~/.oci/config` と API 署名鍵が存在すること）
- 実行ユーザーがテナンシ管理者相当の権限を持つこと
- Always Free リソースは**テナンシのホームリージョン**でのみ作成可能。ホームリージョンが Ampere A1 を提供していること
- Free Tier 制約: VCN は最大 2 本、コンピュートは A1 合計 2 OCPU / 12GB。容量不足時は「out of host capacity」エラーになる

## ディレクトリ構成

```
infra/terraform/
├── versions.tf     # provider / terraform バージョン
├── variables.tf    # 入力変数
├── main.tf         # リソース定義
└── outputs.tf      # 出力（IP など）
```

## 要件

### バージョン・認証

- Terraform は 1.3 以上を要求する
- プロバイダは `oracle/oci` 6.x 以上を使用する
- 認証は `~/.oci/config` の DEFAULT プロファイル（API キー認証）から自動で読む。プロファイルやリージョンは設定で切り替え可能にする

### state の取り扱い

- `terraform.tfstate` にはインフラ情報が入るため **git にコミットしない**
- `.gitignore` に `*.tfstate*`, `.terraform/`, `*.tfvars` を含める（済み）
- state はローカル管理。紛失すると既存リソースを管理不能になるため注意（ADR 0011）

### 入力変数

| 変数 | 必須 | 既定 | 説明 |
| --- | --- | --- | --- |
| `region` | ✅ | - | OCI リージョン（例: ap-tokyo-1） |
| `tenancy_ocid` | ✅ | - | テナンシ OCID（`~/.oci/config` の tenancy と同じ） |
| `compartment_name` | - | `cloud-workplace` | 新規作成するコンパートメント名 |
| `compartment_ocid` | - | 空 | 既存コンパートメントを使う場合のみ指定。空なら新規作成 |
| `availability_domain` | - | 空 | 空なら一覧の先頭 AD を使う（容量不足時は明示指定） |
| `ssh_public_key_path` | - | `~/.ssh/oci_boot.pub` | ブートストラップ用 SSH 公開鍵 |
| `console_public_key_path` | - | `~/.ssh/oci_console_rsa.pub` | シリアルコンソール用公開鍵（**RSA 鍵必須**） |

### 作成するリソース

1. **コンパートメント**（`compartment_ocid` 未指定時のみ新規作成）
   - テナンシ直下に作成。`terraform destroy` で削除できるよう `enable_delete = true` とする
2. **VCN**
   - CIDR `10.0.0.0/16`、DNS ラベル付き。デフォルトリソース（ルートテーブル / セキュリティリスト / DHCP オプション）が自動生成される
3. **インターネットゲートウェイ**
   - 上記 VCN にアタッチし、有効化する
4. **デフォルトルートテーブル**（作成ではなく「管理」）
   - `oci_core_default_route_table` で管理し、ルールは `0.0.0.0/0 → IGW` のみ。ルールは全体置換になる点に注意
5. **デフォルトセキュリティリスト**（作成ではなく「管理」）
   - `oci_core_default_security_list` で管理する。ルールは全体置換
   - ブートストラップ時: ingress は **TCP 22（SSH）のみ**（可能なら自 IP `/32` に絞る）、egress は全許可
   - Phase 5 完了後: **ingress をゼロ**にして再 apply（後述）
6. **パブリックサブネット**
   - CIDR `10.0.0.0/24`、上記デフォルトルートテーブル / セキュリティリストを使用
   - パブリック IP 割当を禁止しない（パブリックサブネット）
7. **インスタンス**
   - Shape `VM.Standard.A1.Flex`、**2 OCPU / 12GB**（Always Free 上限）
   - イメージは **Canonical Ubuntu 24.04 aarch64 の最新**をデータソースで都度解決する（プラットフォームイメージの OCID は更新されるため固定しない）
   - ブートボリューム **100GB**（Always Free 枠 200GB 内）
   - パブリックサブネットに接続し、**エフェメラル公開 IP を自動割当**
   - `ssh_authorized_keys` にブートストラップ用公開鍵を設定
   - A1 プラットフォームイメージは paravirtualized ネットワークが既定。`launch_options` で SR-IOV を指定しないこと
8. **シリアルコンソール接続**（復旧経路）
   - インスタンスに紐付けて作成。公開鍵は **RSA 鍵必須**
   - 制約: 同時 1 クライアント、異常終了時は約 5 分ロック、24 時間で切断

### 出力

- インスタンス OCID
- 公開 IP（VNIC 経由で取得）
- 使用した可用性ドメイン
- シリアルコンソール接続文字列（sensitive 出力）

## 実行手順

事前に SSH 鍵を 2 本用意する:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/oci_boot              # ブートストラップ用
ssh-keygen -t rsa -b 2048 -f ~/.ssh/oci_console_rsa   # シリアルコンソール用（RSA 必須）
```

必須変数（`region`, `tenancy_ocid`）は `terraform.tfvars`（git 管理外）に書くか `-var` で渡す。

```bash
cd infra/terraform
terraform init
terraform fmt
terraform validate
terraform plan -out=tfplan
terraform apply tfplan
```

`terraform output public_ip` でグローバル IP を取得し、ブートストラップ SSH:

```bash
ssh -i ~/.ssh/oci_boot ubuntu@$(terraform output -raw public_ip)
```

## Phase 5: ingress をゼロ化（Tailscale 検証後）

1. インスタンス内で docs/spec/vps-security.md の Phase 1〜4 を実施（Tailscale SSH を別デバイスから検証済みであること）
2. Terraform コードからセキュリティリストの ingress ルールを削除
3. `terraform plan` / `terraform apply` で反映
4. インスタンス内で OpenSSH 停止（`sudo systemctl disable --now ssh`）と UFW 設定（Phase 5〜6）

## 片付け（destroy）と注意点

```bash
terraform destroy
```

- **デフォルトリソース（route table / security list / DHCP options）は VCN と運命を共にする**。`terraform destroy -target=...` でデフォルトリソースだけを消そうとすると、Terraform state からは消えるが OCI 上には「設定が空のまま」残る（公式の制限事項）。個別ターゲット削除はしないこと
- コンパートメントを Terraform 管理下で消すには `enable_delete = true` が必要。またコンパートメントは**空でないと削除できない**ため、先に配下リソースを削除する

## 確認チェックリスト

- [ ] インスタンスが RUNNING
- [ ] ブートストラップ SSH でログインできる（Phase 5 前のみ）
- [ ] シリアルコンソール接続文字列で接続できる
- [ ] 最終的にセキュリティリストの ingress が空
- [ ] `tailscale ssh yamatatsu@<host>` で接続できる

## 参考（公式ドキュメント）

- Terraform Provider 概要: https://registry.terraform.io/providers/oracle/oci/latest/docs
- デフォルト VCN リソースの管理: https://docs.oracle.com/en-us/iaas/Content/ResourceManager/Tasks/terraform-manage-default-vcn-resources.htm
- `oci_core_instance`: https://registry.terraform.io/providers/oracle/oci/latest/docs/resources/core_instance
- `oci_core_instance_console_connection`: https://registry.terraform.io/providers/oracle/oci/latest/docs/resources/core_instance_console_connection
- シリアルコンソール接続: https://docs.oracle.com/iaas/Content/Compute/References/serialconsole.htm
- Terraform チュートリアル（OCI 入門）: https://developer.hashicorp.com/terraform/tutorials/oci-get-started
