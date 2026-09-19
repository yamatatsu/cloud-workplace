# VPS セキュリティ整備

このドキュメントは、Oracle Cloud Infrastructure（OCI）上の Always Free インスタンスを「OCI コンソールのシリアルコンソール接続と Tailscale 以外の入口を塞いだ」安全な状態にするための「あるべき姿」と到達手順を定める。移行元（シンVPS）からの移行作業自体は docs/plans/001-oracle-cloud-migration.md を参照。

## 前提

- クラウド: Oracle Cloud Infrastructure（Always Free 枠）
- インスタンス: `VM.Standard.A1.Flex`（Ampere A1、ARM aarch64）、2 OCPU / 12GB（Always Free 上限に一致）
- OS: Canonical Ubuntu 24.04 Minimal（aarch64）
- Web コンソール（ロックアウト時の最終手段）: **有り（OCI コンソールのシリアルコンソール接続 / Console Connection）**
- 接続方式: Tailscale SSH を主経路とする（ADR 0000, 0007 参照）
- 公開 IP: 存在するが、**インターネットからの到達は OCI 側（セキュリティリスト/NSG）と OS 側（UFW）の二重で全遮断**する

> **最重要原則**: シリアルコンソールは存在するが、ペーストが不便など操作は面倒。そのため、
> 全手順を通して「旧経路が使えることを確認してから、それを閉じる」を徹底する。
> 特に、Tailscale SSH が機能するまで OpenSSH（公開側 22 番）を fallback として残す。

## あるべき姿（ターゲット状態）

| 項目 | あるべき姿 |
| --- | --- |
| アクセス経路 | OCI コンソールのシリアルコンソール接続 + Tailscale SSH **のみ**。それ以外は全て遮断 |
| OCI ネットワーク | セキュリティリスト/NSG の ingress ルールは**ゼロ**（全拒否）。egress は全許可（Tailscale・apt・外部 API 用） |
| OS ファイアウォール | UFW: incoming 既定 deny、outgoing 既定 allow、`tailscale0` のみ入力許可 |
| SSH | Tailscale SSH のみ。OpenSSH（sshd）は停止・無効化。公開側 22 番は開いていない |
| 認証 | パスワード認証なし。tailnet ACL で認可。OCI シリアルコンソールは OS ローカルのパスワードログインのみ |
| root | リモートの root ログイン禁止。`ubuntu` または作業用ユーザー + sudo で運用 |
| Docker | 公開 IP にバインドしない（`127.0.0.1` / Tailscale IP のみ）。DOCKER-USER で tailscale0 以外からの到達を遮断（ADR 0008） |
| アップデート | unattended-upgrades でセキュリティ更新を自動適用 |
| HTTPS | tailscale serve で tailnet 内のみに提供（ADR 0006）。外部公開（Funnel 等）は使わない |

### OCI リソース構成（あるべき姿）

| リソース | 設定 |
| --- | --- |
| コンパートメント | 専用コンパートメント（例: `cloud-workplace`）に集約 |
| VCN | デフォルト 1 本で可（例: `vcn-cloud-workplace`） |
| サブネット | パブリック・サブネット 1 つ（Tailscale は外向き通信のみで動くため） |
| セキュリティリスト | ingress ルールなし（= 全拒否）、egress は 0.0.0.0/0 全許可 |
| NSG | 使わない（セキュリティリストに一本化。運用はどちらか一方に統一） |
| インスタンス | `VM.Standard.A1.Flex`、2 OCPU / 12GB、Canonical Ubuntu 24.04 Minimal（aarch64） |
| ブートボリューム | 100GB（Always Free のブロックボリューム枠 200GB 内。最小 47GB） |
| パブリック IP | エフェメラル（外向き通信用。ingress は全拒否のため攻撃面にならない） |
| コンソール接続 | シリアルコンソール接続を作成し、接続用 SSH 鍵ペアを安全に保管 |

> **注意**: Always Free の Ampere A1 は **合計 2 OCPU / 12GB まで**（1 台に全割当）。ARM（aarch64）のため、Docker イメージは arm64 対応が必須（LibreChat / MongoDB の arm64 イメージ有無は移行計画で検証する）。

## 手順

各フェーズ末尾に「検証」を置き、検証を通るまで次フェーズに進まない。

### Phase 0: 初期ブートストラップ（一時的な SSH）

OCI インスタンス作成時に SSH 公開鍵を登録し、セキュリティリストに**一時的に** 22 番の ingress ルール（可能なら自分のグローバル IP に限定）を追加する。この窓は Tailscale 確立後に必ず閉じる。

```
ssh ubuntu@<インスタンスの公開IP>
```

- 検証: `ubuntu` ユーザーで SSH ログインできる。

### Phase 1: 基本更新と自動更新の導入

```
sudo apt update && sudo apt upgrade -y
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure --priority=low unattended-upgrades
```

- 検証: プロンプトで「セキュリティ更新を自動適用」を有効にしたことを確認。

### Phase 2: Tailscale の導入と接続

```
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
tailscale ip -4        # tailnet 内の IP（100.x.y.z）を控える
```

- Tailscale 管理者コンソールにデバイスが表示されることを確認。
- MagicDNS を有効にすると `<host>.ts.net` で名前解決できる（推奨）。
- 検証: `tailscale ip -4` が 100.x.y.z を返す。

### Phase 3: 作業用ユーザーの作成

```
sudo adduser yamatatsu
sudo usermod -aG sudo yamatatsu
```

- 以降は `ubuntu` / root でなく `yamatatsu` + `sudo` で運用する。
- シリアルコンソール復旧用に `yamatatsu` のローカルパスワードを設定しておく（シリアルコンソールはローカルログインのためパスワードが必要）。

### Phase 4: Tailscale SSH の有効化と検証

1. Tailscale 管理者コンソールで Tailscale SSH を有効化し、ACL で SSH ルールを設定する（対象ユーザーを `yamatatsu` に限定、root は許可しない）。
2. サーバ側で SSH を有効化:
   ```
   sudo tailscale up --ssh
   ```
3. クライアントから接続:
   ```
   tailscale ssh yamatatsu@<host>
   ```

- 検証: **別のデバイスから** `tailscale ssh yamatatsu@<host>` でログインできる。
- 検証: `herdr --remote` が動作する前提として、標準 `ssh yamatatsu@<host>` でも接続できること（`tailscale configure ssh` 等で ProxyCommand を整備）。

> ここまでは **OpenSSH と公開側 22 番を止めない**。fallback として残したまま次へ進む。

### Phase 5: OCI 側 ingress の閉鎖と OpenSSH の停止

Tailscale SSH が安定動作することを確認した後に実施する。

1. OCI コンソールでセキュリティリストの ingress ルール（22 番）を**削除**し、ingress ゼロにする。
2. OpenSSH を停止・無効化:
   ```
   sudo systemctl disable --now ssh
   ```

- 検証: tailscale 経由で入り直せることを再確認。
- 検証: 公開 IP の 22 番に外部から接続できないこと。

### Phase 6: UFW で不要な入力を遮断（二重化）

OCI 側を誤って開けた場合の防衛として、OS 側も閉じる。

```
sudo apt install -y ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow in on tailscale0
sudo ufw enable
sudo ufw status verbose
```

- 送信（outgoing）はデフォルト許可（Tailscale の 41641/udp、apt、モデル API 等の外向き通信を阻害しない）。
- 受信（incoming）はデフォルト拒否、`tailscale0` のみ許可。
- 検証: tailscale 経由の接続は維持されたまま、公開 IP 側に何もポートが開いていないことを確認（`ufw status` と外部からのスキャン）。

### Phase 7: Docker の公開経路対策

Docker は iptables を直接操作し UFW をバイパスするため、追加対策が必須（LibreChat 導入前に実施）。

1. **ポートのバインド先を限定**する。Compose では `0.0.0.0` に晒さず `127.0.0.1` や Tailscale IP にバインドする（ADR 0008）。
2. **DOCKER-USER チェーン**で tailscale 以外のインターフェースからのコンテナ到達を遮断する。
   ```
   sudo iptables -I DOCKER-USER -i ! tailscale0 -j DROP
   ```
   - このルールは再起動で消えるため、永続化（`netfilter-persistent` や UFW の `before.rules`）を行う。
- 検証: コンテナを起動した状態で、公開 IP からサービスへ到達できないことを確認する。
- 補足: 本インスタンスは ARM（aarch64）のため、使用するイメージが arm64 対応であることを各コンテナで確認する。

### Phase 8: その他の封鎖と確認

- **fail2ban**: 公開されている SSH ポートが無いため必須ではない（導入は任意）。
- **IPv6**: VCN/サブネットで IPv6 を有効化しない限り OCI 側に IPv6 アドレスは付かない。OS 側で使用しない場合は無効化を検討。
- **タイム同期**: `systemd-timesyncd`（または chrony）が有効であることを確認（Tailscale / TLS で時刻ズレ防止）。
- **パッケージ**: 使用しないサービスが起動していないかを確認。

## 検証チェックリスト

- [ ] `tailscale ssh yamatatsu@<host>` で接続できる
- [ ] 標準 `ssh yamatatsu@<host>`（ProxyCommand 設定後）でも接続できる
- [ ] OCI セキュリティリストの ingress ルールがゼロ
- [ ] 公開 IP にポートが露出していない（外部スキャンで確認）
- [ ] root でのリモートログインができない
- [ ] パスワード認証が使えない（tailnet ACL のみ。シリアルコンソールのローカルログインを除く）
- [ ] `ufw status` が `incoming: deny` かつ tailscale0 のみ許可
- [ ] Docker コンテナも公開 IP から到達できない
- [ ] シリアルコンソール接続で `yamatatsu` がローカルログインできる
- [ ] unattended-upgrades が有効

## 復旧（ロックアウト時）

公開 SSH / Tailscale が塞がっても、OCI コンソールの **シリアルコンソール接続（Console Connection）** から直接ログインできるため、これを最終手段とする（シンVPS の noVNC に相当）。

- **シリアルコンソール接続**: sshd や Tailscale に依存せず常に使える最強の復旧経路。OCI コンソール → コンピュート → インスタンス → 「コンソール接続」から作成し、Cloud Shell 経由で接続する。接続用 SSH 鍵ペアの秘密鍵を紛失しないこと。ペーストが不便な点に留意。
- シリアルコンソールは OS のローカルログインのため、`yamatatsu` のローカルパスワードを設定・保管しておく（Phase 3）。
- Tailscale が生きていれば、tailnet 内の別デバイスから `tailscale ssh` で入り直せる（復旧手段を複数デバイスに確保）。
- Tailscale のサービスや `tailscale0` を不用意に止めない・UFW / セキュリティリストで閉じない。
- 公開側の接続（一時 SSH）を完全に塞ぐ前に、必ず Tailscale SSH とシリアルコンソールの両方で復旧経路を検証しておく。
