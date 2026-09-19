# ADR 0011: OCI リソースの管理に Terraform を採用

- Status: 決定
- Date: 2026-09-14

## Context

ADR 0010 で VPS を OCI に移行することを決定した。OCI 上のリソース（コンパートメント、VCN、サブネット、インスタンス、シリアルコンソール接続）の作成方法として、3 つの計画を用意した:

1. Web コンソールで手動作成（docs/plans/001-oracle-cloud-migration.md）
2. OCI CLI で作成（docs/plans/002-oci-cli-vm-setup.md）
3. Terraform で作成（docs/plans/003-oci-terraform-vm-setup.md）

実際には候補 1 でコンパートメントと VCN 周辺まで作成したが、手動作業は再現性がなく、設定内容がドキュメントと乖離していくリスクがある。また VC Wizard 方式は不要なリソース（NAT ゲートウェイ等）も作られてしまう。作り直しを決め、作成済みリソースは全て削除した。

## Decision

候補 3 を採用し、OCI リソースは **Terraform（Oracle 公式 `oracle/oci` プロバイダ）で宣言的に管理**する。コードは `infra/terraform/` に置き、要件は docs/plans/003-oci-terraform-vm-setup.md に記す。

- 認証は `~/.oci/config` の API キー認証（OCI CLI と共通）を使う。
- `terraform.tfstate` はローカル管理とし、**git にコミットしない**（state・`.terraform/`・`*.tfvars` は gitignore 済み）。
- コンソール / CLI での手動変更は行わず、変更は Terraform 経由に統一する。

## Consequences

- プラス: インフラ構成がコードとして保存され、再現・再作成が容易。変更履歴が git で追える。
- プラス: 不要なリソース（NAT / Service Gateway / プライベートサブネット）を作らない最小構成を保てる。`terraform destroy` で一括片付けができる。
- プラス: Phase 5 の ingress ゼロ化のような段階的な変更も、コード編集 + apply として手順化できる。
- マイナス: state をローカル管理するため、state ファイルの紛失は既存リソースの管理不能を意味する（再 import は可能だが手間）。バックアップかリモート backend への移行を将来検討する。
- マイナス: Web コンソール等での手動変更がドリフト（state との乖離）を生むため、運用上 Terraform 以外での変更を禁止する規律が必要。
- マイナス: 作業端末に Terraform のインストールが必要になる。
