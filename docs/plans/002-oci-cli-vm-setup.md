# OCI CLI でゼロから VM を起動する手順

- 関連: docs/plans/001-oracle-cloud-migration.md（Web コンソール版）、docs/spec/vps-security.md、ADR 0010
- 目的: OCI CLI のみで、コンパートメント → VCN → サブネット → インスタンス → シリアルコンソール接続までを一気通貫で作成する
- 特徴: CLI なので**必要なリソースだけを作る**。VCN ウィザードと違い NAT ゲートウェイ / Service Gateway / プライベートサブネットは**作らない**

> **2026-09-14 追記**: 本書の CLI 手順は実施しないことになった。Terraform 方式（ADR 0011、docs/plans/003-oci-terraform-vm-setup.md）を採用したため。ただし Step 1 の OCI CLI セットアップ（`oci setup config` による `~/.oci/config` と API キー作成）は Terraform の認証にも使うため実施済み。本書は手順の記録として残す。

## 前提

- OCI アカウント作成済み（ホームリージョンで操作する。Always Free はホームリージョン限定）
- 作業端末は macOS / Linux（以下 macOS 前提で記載）
- CLI を実行するユーザーはテナンシ管理者相当の権限を持つこと（`manage` 権限がないと各種 `create` が失敗する）

## 変数の準備

以降のコマンドで使う変数をまとめる。各所で取得した OCID を順に代入していく。

```bash
TENANCY_OCID="ocid1.tenancy.oc1..xxxx"     # テナンシ OCID（~/.oci/config の tenancy= と同じ）
COMPARTMENT_OCID=""                        # Step 2 で取得
VCN_OCID=""                                # Step 3 で取得
IGW_OCID=""                                # Step 4 で取得
RT_OCID=""                                 # デフォルトルートテーブル（Step 4 で取得）
SL_OCID=""                                 # デフォルトセキュリティリスト（Step 5 で取得）
SUBNET_OCID=""                             # Step 6 で取得
AD_NAME=""                                 # Step 7 で取得
IMAGE_OCID=""                              # Step 8 で取得
INSTANCE_OCID=""                           # Step 9 で取得
```

## Step 1: OCI CLI のインストールと初期設定

### 1-1. インストール

macOS（Homebrew）:

```bash
brew install oci-cli
```

または公式インストールスクリプト（macOS/Linux 共通）:

```bash
bash -c "$(curl -L https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh)"
```

- 確認: `oci --version`
- 代替: OCI コンソールの **Cloud Shell**（ブラウザ内ターミナル）には CLI が認証済みでプリインストールされている。ローカルに入れたくない場合はこちらで後続手順を実行してもよい。

### 1-2. 初期設定（API キー認証）

```bash
oci setup config
```

対話で以下を入力し、`~/.oci/config` と API 鍵ペア（`~/.oci/oci_api_key.pem` / `~/.oci/oci_api_key_public.pem`）が生成される:

- Tenancy OCID（コンソール: 右上プロフィール → Tenancy → OCID）
- User OCID（コンソール: 右上プロフィール → User settings → OCID）
- リージョン（例: `ap-tokyo-1` / `ap-osaka-1`）
- 新しい API 署名鍵を生成するか → `Y`（RSA 2048bit PEM が生成される）

### 1-3. API 公開鍵をユーザーに登録

コンソールで登録: 右上プロフィール → **My profile → API keys → Add API key** → 公開鍵（`~/.oci/oci_api_key_public.pem`）を貼る。

CLI で登録する場合:

```bash
oci iam user api-key upload --user-id <User OCID> --key-file ~/.oci/oci_api_key_public.pem
```

### 1-4. 動作確認

```bash
oci iam availability-domain list --compartment-id $TENANCY_OCID
```

リージョン内の AD 一覧（例: `xxxx:AP-TOKYO-1-AD-1`）が JSON で返れば認証成功。これを `AD_NAME` に使う。

## Step 2: コンパートメント作成

```bash
oci iam compartment create \
  --compartment-id $TENANCY_OCID \
  --name cloud-workplace \
  --description "cloud-workplace 移行用" \
  --query 'data.id' --raw-output
```

- 返り値の OCID を `COMPARTMENT_OCID` にセット。
- 反映に数秒かかることがある。

## Step 3: VCN 作成

```bash
VCN_OCID=$(oci network vcn create \
  --compartment-id $COMPARTMENT_OCID \
  --cidr-blocks '["10.0.0.0/16"]' \
  --display-name vcn-cloud-workplace \
  --dns-label vcnworkplace \
  --query 'data.id' --raw-output)
echo $VCN_OCID
```

- VCN 作成時に**デフォルトのルートテーブル・セキュリティリスト・DHCP オプションが自動生成**される（削除不可だが内容は変更可能）。
- デフォルトリソースの OCID を取得しておく:

```bash
RT_OCID=$(oci network vcn get --vcn-id $VCN_OCID --query 'data."default-route-table-id"' --raw-output)
SL_OCID=$(oci network vcn get --vcn-id $VCN_OCID --query 'data."default-security-list-id"' --raw-output)
echo $RT_OCID $SL_OCID
```

## Step 4: インターネットゲートウェイ作成とルート設定

```bash
IGW_OCID=$(oci network internet-gateway create \
  --compartment-id $COMPARTMENT_OCID \
  --vcn-id $VCN_OCID \
  --is-enabled true \
  --display-name igw-cloud-workplace \
  --query 'data.id' --raw-output)
```

デフォルトルートテーブルに `0.0.0.0/0 → IGW` を追加（`--force` で既存ルールを置き換える）:

```bash
oci network route-table update \
  --rt-id $RT_OCID \
  --route-rules "[{\"destination\":\"0.0.0.0/0\",\"destinationType\":\"CIDR_BLOCK\",\"networkEntityId\":\"$IGW_OCID\"}]" \
  --force
```

> **注意**: ルートテーブル / セキュリティリストの `update` はルール全体を**置き換え**る。既存ルールを残したい場合は先に `get` で取得してマージすること。ここでは新規 VCN のため置き換えで問題ない。

## Step 5: セキュリティリスト（ブートストラップ用に 22 番のみ許可）

**初期状態（Phase 0〜4 用）**: ingress に SSH(22) のみ、egress は全許可。可能なら `source` を自分のグローバル IP（`x.x.x.x/32`）に絞る。

```bash
oci network security-list update \
  --security-list-id $SL_OCID \
  --ingress-security-rules '[{"source":"0.0.0.0/0","protocol":"6","isStateless":false,"tcpOptions":{"destinationPortRange":{"min":22,"max":22}}}]' \
  --egress-security-rules '[{"destination":"0.0.0.0/0","protocol":"all","isStateless":false}]' \
  --force
```

> 最終状態（Phase 5 完了後）は **ingress を空にする**。後述「Step 11」参照。

## Step 6: パブリックサブネット作成

```bash
SUBNET_OCID=$(oci network subnet create \
  --compartment-id $COMPARTMENT_OCID \
  --vcn-id $VCN_OCID \
  --cidr-block 10.0.0.0/24 \
  --display-name public-subnet \
  --dns-label pub \
  --route-table-id $RT_OCID \
  --security-list-ids "[\"$SL_OCID\"]" \
  --query 'data.id' --raw-output)
```

- `--prohibit-public-ip-on-vnic` を指定しない（= false）のでパブリックサブネットになる。

## Step 7: 可用性ドメインの決定

```bash
oci iam availability-domain list --compartment-id $TENANCY_OCID \
  --query 'data[].name' --output table
```

例: `AD_NAME="xxxx:AP-TOKYO-1-AD-1"` をセット。容量不足（`out of host capacity`）の場合は別 AD に変えて再試行。

## Step 8: Ubuntu（aarch64）イメージの OCID を取得

A1.Flex は ARM のため **aarch64 イメージ必須**。最新の 24.04 aarch64 イメージを拾う:

```bash
oci compute image list \
  --compartment-id $TENANCY_OCID \
  --operating-system "Canonical Ubuntu" \
  --all \
  --query 'data[?contains("display-name",`24.04`) && contains("display-name",`aarch64`)] | sort_by(@,&"time-created")[-1].{id:id,name:"display-name"}' \
  --output table
```

- 返った `id` を `IMAGE_OCID` にセット（例: `Canonical-Ubuntu-24.04-Minimal-aarch64-...` や `Canonical-Ubuntu-24.04-aarch64-...`）。
- プラットフォームイメージは定期的に更新され、古い OCID は `image list` に出なくなるため、**都度取得する**。
- 迷ったらコンソールのインスタンス作成画面でイメージ名を確認し、同じ文字列で `contains()` を調整する。

## Step 9: インスタンス作成

ブートストラップ用 SSH 公開鍵を用意（なければ生成）:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/oci_boot -C oci-boot
```

インスタンスを起動:

```bash
INSTANCE_OCID=$(oci compute instance launch \
  --availability-domain "$AD_NAME" \
  --compartment-id $COMPARTMENT_OCID \
  --shape VM.Standard.A1.Flex \
  --shape-config '{"ocpus":2,"memoryInGBs":12}' \
  --display-name vps-workplace \
  --image-id $IMAGE_OCID \
  --subnet-id $SUBNET_OCID \
  --assign-public-ip true \
  --ssh-authorized-keys-file ~/.ssh/oci_boot.pub \
  --boot-volume-size-in-gbs 100 \
  --wait-for-state RUNNING \
  --query 'data.id' --raw-output)
echo $INSTANCE_OCID
```

- Shape: `VM.Standard.A1.Flex`、`--shape-config` で **2 OCPU / 12GB**（Always Free 上限）。
- ブートボリューム: 100GB（Always Free 枠 200GB 内）。
- A1 プラットフォームイメージは paravirtualized ネットワークが既定（SR-IOV は非推奨/失敗する）。launch 時にネットワーク種別を指定しないこと。

公開 IP を取得:

```bash
PUBLIC_IP=$(oci compute instance list-vnics --instance-id $INSTANCE_OCID \
  --query 'data[0]."public-ip"' --raw-output)
echo $PUBLIC_IP
```

## Step 10: シリアルコンソール接続（復旧経路）の作成

シリアルコンソール接続は **RSA 鍵必須**。専用鍵を生成:

```bash
ssh-keygen -t rsa -b 2048 -f ~/.ssh/oci_console_rsa -C oci-console
```

接続を作成:

```bash
CONSOLE_OCID=$(oci compute instance-console-connection create \
  --instance-id $INSTANCE_OCID \
  --ssh-public-key-file ~/.ssh/oci_console_rsa.pub \
  --query 'data.id' --raw-output)
echo $CONSOLE_OCID
```

接続文字列を取得（状態が ACTIVE になってから）:

```bash
oci compute instance-console-connection get \
  --instance-console-connection-id $CONSOLE_OCID \
  --query 'data."connection-string"' --raw-output
```

- 出力された `ssh -o ProxyCommand=...` 文字列をターミナルで実行して接続（ProxyCommand 内でも同じ `-i ~/.ssh/oci_console_rsa` を指定）。
- **ブラウザ完結がよければ、コンソールのインスタンス詳細 → Console connection →「Launch Cloud Shell connection」**でもよい（接続と一時鍵を自動生成）。
- 制約: 同時 1 クライアント、異常終了時は約 5 分ロック、24 時間で切断、使い終わったら削除。

## Step 11: セキュリティ整備（インスタンス内）と ingress のゼロ化

1. まず `ssh -i ~/.ssh/oci_boot ubuntu@$PUBLIC_IP` で入り、docs/spec/vps-security.md の **Phase 1〜4**（更新 / Tailscale / yamatatsu / Tailscale SSH）を実施。
2. Tailscale SSH を**別デバイスから検証**したら、**OCI 側 ingress をゼロ化**（Phase 5）:

```bash
oci network security-list update \
  --security-list-id $SL_OCID \
  --ingress-security-rules '[]' \
  --egress-security-rules '[{"destination":"0.0.0.0/0","protocol":"all","isStateless":false}]' \
  --force
```

3. インスタンス内で OpenSSH 停止（`sudo systemctl disable --now ssh`）と UFW 設定（Phase 5〜6）を行う。

## 確認チェックリスト

- [ ] `oci compute instance get --instance-id $INSTANCE_OCID` が RUNNING
- [ ] `ssh -i ~/.ssh/oci_boot ubuntu@$PUBLIC_IP` でログインできる（Phase 5 前のみ）
- [ ] シリアルコンソール接続文字列で接続できる
- [ ] 最終的にセキュリティリストの ingress が空
- [ ] `tailscale ssh yamatatsu@<host>` で接続できる

## 参考（公式ドキュメント）

- CLI クイックスタート: https://docs.oracle.com/en-us/iaas/Content/GSG/Tasks/gettingstartedwiththeCLI.htm
- CLI インストール: https://docs.oracle.com/iaas/Content/API/SDKDocs/cliinstall.htm
- VCN 作成: https://docs.oracle.com/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/network/vcn/create.html
- インスタンス作成: https://docs.oracle.com/iaas/Content/Compute/Tasks/launchinginstance.htm
- イメージ一覧: https://docs.oracle.com/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/compute/image/list.html
- シリアルコンソール接続: https://docs.oracle.com/iaas/Content/Compute/References/serialconsole.htm
