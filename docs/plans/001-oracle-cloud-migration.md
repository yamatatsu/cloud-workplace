# 移行計画: シンVPS → Oracle Cloud（Always Free / Ampere A1）

- 関連: ADR 0010（移行の決定）、docs/spec/vps-security.md（あるべき姿）
- 状態: **実施せず（破棄）**
- 前提: OCI アカウント作成済み・リソース未作成

> **2026-09-14 追記**: 本書の Web コンソール手順は実施しないことになった。Step 1 のコンパートメント / VCN 作成まで一時的にコンソールで実施したが、再現性の観点から Terraform 方式（ADR 0011、docs/plans/003-oci-terraform-vm-setup.md）に切り替え、作成済みリソースは全て削除済み。本書は手順の記録として残す。

## 目的

シンVPS 上の環境（LibreChat + MongoDB、OpenCode 実行環境）を OCI Always Free 枠の `VM.Standard.A1.Flex`（2 OCPU / 12GB, Ubuntu 24.04 aarch64）に移行する。アクセス経路は OCI シリアルコンソール接続と Tailscale のみに限定する。

## 作業ステップ

### Step 1: OCI リソースの作成（Web コンソール）

> **CLI で行う場合は docs/plans/002-oci-cli-vm-setup.md、Terraform で行う場合は docs/plans/003-oci-terraform-vm-setup.md を参照**（いずれもコンパートメント〜シリアルコンソール接続まで一気通貫。不要な NAT/Service Gateway を作らない点でも簡潔）。

前提（公式ドキュメントより）:

- Always Free リソースは **テナンシのホームリージョン** でのみ作成できる。ホームリージョンが Ampere A1 を提供していることを確認する。
- Free Tier テナンシで作成できる **VCN は最大 2 本**、コンピュートは **A1 合計 2 OCPU / 12GB**（1,500 OCPU 時間・9,000 GB 時間/月）。
- 容量不足時は「out of host capacity」エラーになる → **別の可用性ドメインを試す or 時間を置く**。

1. **コンパートメント作成**
   - ナビゲーションメニュー → **Identity → Compartments → Create Compartment**。名前 `cloud-workplace`。
2. **VCN 作成**
   - **Networking → Virtual Cloud Networks → Start VCN Wizard** →「**Create VCN with Internet Connectivity**」を選択。
   - このウィザードはパブリック/プライベートサブネット、インターネットゲートウェイ、NAT ゲートウェイ、ルートルールを自動構成する。名前 `vcn-cloud-workplace`。
   - **料金**: VCN およびゲートウェイ（IGW/NAT/Service）の作成・使用自体は無料。課金されるのは外向きデータ転送のみ（月 10TB まで無料。本用途は余裕で枠内）。NAT 経由でも IGW 経由でもデータ転送課金は同じ。
   - **本設計はパブリックサブネット + 公開 IP + IGW で外向き通信するため NAT ゲートウェイは不要**。また OCI サービス（Object Storage 等）を使わないため **Service Gateway も不要**。ウィザード作成後に **NAT ゲートウェイ・Service Gateway・未使用のプライベートサブネットを削除**して構成を最小化してよい（削除順: プライベートサブネット → NAT → Service Gateway）。
   - 手動作成でも可（その場合はパブリックサブネット + インターネットゲートウェイ + ルートテーブル `0.0.0.0/0 → IGW` を用意）。
3. **セキュリティリストの確認**
   - OCI の VCN には**デフォルトセキュリティリスト**が付き、初期ルールとして「stateful ingress: TCP **22 (SSH)** from `0.0.0.0/0`」と「stateful ingress: ICMP type 3 code 4（Path MTU Discovery 用）」が入る（ping 用の ICMP type 8 は含まれない）。
   - ブートストラップ中は 22 番を残す。可能なら **Source CIDR を自宅/作業端末のグローバル IP（`x.x.x.x/32`）に絞る**。
   - Step 2 の Phase 5 で 22 番を削除し、最終的に**ingress ルールをゼロ**にする。
   - 補足: OCI は一般に NSG の利用を推奨しているが、本設計はサブネット単位で一括拒否したいためセキュリティリストに一本化する（docs/spec/vps-security.md の構成に合わせる）。
4. **インスタンス作成**（Compute → Instances → Create instance）
   - **Basic Information**
     - Name: 任意（例 `vps-workplace`）、Compartment: `cloud-workplace`
     - Availability domain: 任意（容量不足時は別 AD を試す）
     - Capacity type: **On-demand**（preemptible は回収されるため不可）
   - **Image and Shape**
     - Change image → Platform Images → **Ubuntu** → バージョン選択（例 24.04）。**ARM 用の aarch64/Ampere 対応イメージ**を選ぶ。
     - Change shape → Instance type: Virtual machine → Shape series: **Ampere** → `VM.Standard.A1.Flex`。
     - Number of OCPUs: **2**、Amount of memory: **12 GB**（スライダー。A1 の Always Free 上限）。
   - **Networking**
     - VCN: `vcn-cloud-workplace`、Subnet: パブリックサブネット
     - Primary VNIC: **Automatically assign private IPv4** と **Automatically assign public IPv4**（エフェメラル）を選択。
   - **Add SSH keys**
     - ブートストラップ用に**自分で生成した RSA 公開鍵をアップロード**（Phase 5 で不要になる）。OCI 生成鍵でも可だが、後述のローカルシリアルコンソール接続は **RSA 鍵必須**な点に注意。
   - **Storage**
     - 「Specify a custom boot volume size」を選び **100GB**（Always Free ブロック 200GB 内。デフォルト 50GB、最小 47〜50GB、最大 200GB）。
   - **Security（任意）**
     - Shielded instance は有効化すると起動後に名前以外を変更できなくなる。不要ならオフ。
   - Create → 数分で Running になる。
5. **シリアルコンソール接続の確立**（noVNC の代替・最終復旧経路）
   - **Cloud Shell 経由（推奨・ブラウザ完結）**: インスタンス詳細 → Resources → **Console connection** → 「**Launch Cloud Shell connection**」。Cloud Shell がコンソール接続と一時 SSH 鍵を自動生成する。必要権限は IAM の `manage instance-console-connection` と `read instance` のみ。
   - **ローカル接続（任意）**: 同画面で「**Create local connection**」→ **RSA 公開鍵**を指定 → 状態が **Active** になったら Actions →「Copy serial console connection for Linux/Mac」で得た SSH 文字列（ProxyCommand 経由・ポート 443）で接続。
   - 制約（公式）:
     - コンソール接続は **同時 1 クライアントのみ**。クライアント異常終了時は約 **5 分間ロック**される。
     - 接続を放置すると **24 時間でセッション切断**。使い終わったら接続を削除する。
   - ログインには **パスワード付きユーザー**が必要（OCI は `opc`/`ubuntu` にデフォルトパスワードを設定しない）。Ubuntu の既定ユーザーは `ubuntu`。Step 2 Phase 3 で作成する `yamatatsu` にローカルパスワードを設定しておく。
   - 補足: Cloud Shell は既定でホームリージョン内の OCI 内部リソースへのネットワークのみ許可されるが、シリアルコンソール接続は OCI 内部のため問題ない。

- 完了条件: インスタンスが Running で、Cloud Shell のシリアルコンソールに OS のログインプロンプト（`ubuntu login:` 等）が見える。

### Step 2: インスタンスのセキュリティ整備

docs/spec/vps-security.md の Phase 0〜6 を順に実施する（各 Phase の検証を通ってから次へ）。

- Phase 0: 一時 SSH（`ubuntu` ユーザー）でログイン
- Phase 1: 基本更新 + unattended-upgrades
- Phase 2: Tailscale 導入（`tailscale up`）
- Phase 3: 作業ユーザー `yamatatsu` 作成（ローカルパスワードも設定: シリアルコンソール復旧用）
- Phase 4: Tailscale SSH 有効化・別デバイスから検証
- Phase 5: **セキュリティリストの ingress ルールを全削除（ゼロ化）** + OpenSSH 停止
- Phase 6: UFW 設定（incoming deny / tailscale0 のみ許可）

- 完了条件: vps-security.md の検証チェックリストのうち Docker 関連以外が全て ✅。

### Step 3: ARM（aarch64）対応の検証

- `ghcr.io/danny-avila/librechat` と `mongo:8.0` の arm64 イメージ有無を確認（`docker manifest inspect` 等）。
- 非対応の場合: 対応バージョンへの変更 or 代替検討。LibreChat 非対応なら ADR 0009/0010 の見直しを検討。

### Step 4: サービス移行（LibreChat + MongoDB）

1. 新インスタンスに git リポジトリを clone（ADR 0002: git リモートが真実の源）。
2. `.env` を新インスタンスにコピー（ADR 0005。シークレットは手動で安全に転送）。
3. Phase 7（Docker 公開経路対策）を実施してからコンテナ起動。
   - ※ `docker-compose.yml` の `ports: 3080:3080` は `0.0.0.0` バインドになるため、`127.0.0.1:3080:3080` への修正を検討（ADR 0008）。
4. MongoDB データ移行: 旧 VPS で `mongodump` → 新 VPS で `mongorestore`（tailnet 経由で転送）。
5. tailscale serve で HTTPS 提供を再設定（ADR 0006）。
6. 新旧で LibreChat の動作を比較確認（ログイン・チャット履歴・API キー）。

- 完了条件: 新インスタンス上で LibreChat が旧環境と同等に動作し、公開 IP から到達不可であること。

### Step 5: OpenCode / herdr 環境の移行

- mise / OpenCode / herdr を新インスタンスにセットアップ（`setup-vps/init.sh` を参照・必要なら ARM 対応に修正）。
- クライアント側の ProxyCommand / MagicDNS 名を新ホストに合わせて更新（ADR 0003, 0007）。

### Step 6: カットオーバーと旧 VPS の解約

1. 旧 VPS の Tailscale デバイスを無効化・削除し、tailnet 上のホスト名の衝突を解消。
2. 一定期間（目安: 1〜2 週間）並行稼働で問題ないことを確認。
3. シンVPS を解約。`.env` 等のシークレットが旧 VPS に残っていないことを確認。

### Step 7: ドキュメント更新

- README.md の VPS 記述を OCI に更新。
- setup-vps/init.sh が ARM/OCI 前提になった点を反映。

## リスクと対策

| リスク | 対策 |
| --- | --- |
| Ampere A1 の容量不足でインスタンスを作成できない | 別 AD/リージョンで試行。Home Region は A1 提供リージョンを選ぶ |
| arm64 非対応イメージがある | Step 3 で事前検証。非対応なら代替イメージ/バージョンに変更 |
| 移行中のロックアウト | シリアルコンソール接続を先に確立・検証してから ingress を閉じる |
| データ移行漏れ（MongoDB 等） | mongodump/restore 後に件数・内容を目視確認。並行稼働期間で検証 |
| 無料枠ポリシー変更 | 現行ルール（合計 2 OCPU / 12GB）内で運用。OCI の告知を定期的に確認 |
| **アイドルインスタンスの回収** | Always Free は 7 日間で CPU p95 < 20%・ネットワーク < 20%・メモリ < 20%（A1）だと回収されうる。常時稼働のワークロードを載せ、必要なら監視・定期アクセスで回避 |

## 参考（公式ドキュメント）

- Always Free リソース: https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm
- インスタンス作成: https://docs.oracle.com/iaas/Content/Compute/Tasks/launchinginstance.htm
- シリアルコンソール接続: https://docs.oracle.com/iaas/Content/Compute/References/serialconsole.htm
- セキュリティリスト: https://docs.oracle.com/en-us/iaas/Content/Network/Concepts/securitylists.htm
- セキュリティルール: https://docs.oracle.com/en-us/iaas/Content/Network/Concepts/securityrules.htm
