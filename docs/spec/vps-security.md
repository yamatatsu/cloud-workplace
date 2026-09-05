# VPS セキュリティ整備

このドキュメントは、シンVPS（Ubuntu）を「Tailscale 以外の入口を塞いだ」安全な状態にするまでの手順を定める。

## 前提

- OS: Ubuntu
- 初期状態: root アカウントへの SSH（パスワード認証）が可能
- Web コンソール（ロックアウト時の最終手段）: **有り（noVNC）**
- 接続方式: Tailscale SSH を主経路とする（ADR 0000 参照）

> **最重要原則**: noVNC コンソールは存在するが、ロックアウトしたら復旧が面倒（peaste が不便など）。そのため、
> 全手順を通して「旧経路が使えることを確認してから、それを閉じる」を徹底する。
> 特に、Tailscale SSH が機能するまで OpenSSH を fallback として残す。

## 方針サマリ

| 項目 | 方針 |
| --- | --- |
| SSH アクセス | Tailscale SSH を主経路、確認まで OpenSSH を fallback で残す |
| 認証 | パスワード認証を廃し、tailnet ACL で認可 |
| root | リモートの root ログインを禁止し、sudo ユーザーで運用 |
| ファイアウォール | UFW で tailscale0 以外の入力を deny |
| アップデート | unattended-upgrades で自動セキュリティ更新 |
| Docker | ポートを公開 IP にバインドせず、DOCKER-USER で遮断 |

## 手順

各フェーズ末尾に「検証」を置き、検証を通るまで次フェーズに進まない。

### Phase 0: 初期ブートストラップ（root パスワード SSH）

初回のみ root パスワードでログインする。以降はこの窓をなるべく早く閉じる。

```
ssh root@<VPSの公開IP>
```

### Phase 1: 基本更新と自動更新の導入

```
apt update && apt upgrade -y
apt install -y unattended-upgrades
dpkg-reconfigure --priority=low unattended-upgrades
```

- 検証: プロンプトで「セキュリティ更新を自動適用」を有効にしたことを確認。

### Phase 2: Tailscale の導入と接続

```
curl -fsSL https://tailscale.com/install.sh | sh
tailscale up
tailscale ip -4        # tailnet 内の IP（100.x.y.z）を控える
```

- Tailscale 管理者コンソールにデバイスが表示されることを確認。
- MagicDNS を有効にすると `<host>.ts.net` で名前解決できる（推奨）。
- 検証: `tailscale ip -4` が 100.x.y.z を返す。

### Phase 3: 作業用ユーザーの作成

```
adduser yamatatsu
usermod -aG sudo yamatatsu
```

- 以降は root でなく `yamatatsu` + `sudo` で運用する。

### Phase 4: Tailscale SSH の有効化と検証

1. Tailscale 管理者コンソールで Tailscale SSH（Feature preview）を有効化し、ACL で SSH ルールを設定する（対象ユーザーを `yamatatsu` に限定、root は許可しない）。
2. クライアント側で SSH を有効化:
   ```
   tailscale up --ssh
   ```
3. `ssh yamatatsu@<host>` と同様の接続を Tailscale SSH で行う:
   ```
   tailscale ssh yamatatsu@<host>
   ```

- 検証: **別のデバイスから** `tailscale ssh yamatatsu@<host>` でログインできる。
- 検証: `herdr --remote` が動作する前提として、`ssh yamatatsu@<host>`（標準 ssh コマンド）でも接続できること（`tailscale configure ssh` 等で ProxyCommand を整備）。

> ここまでは **OpenSSH を止めない**。fallback として残したまま次へ進む。

### Phase 5: OpenSSH の閉鎖（fallback の解消）

Tailscale SSH が安定動作することを確認した後に OpenSSH を停止する。

```
systemctl disable --now ssh
```

- 検証: tailscale 経由で入り直せることを再確認。
- 補助: OpenSSH を残す場合は、公開側で 22 を塞ぎ、`PasswordAuthentication no` / `PermitRootLogin no` を設定する。

### Phase 6: UFW で不要な入力を遮断

```
apt install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow in on tailscale0
ufw enable
ufw status verbose
```

- 送信（outgoing）はデフォルト許可にし、Tailscale の通信（41641/udp）や apt/モデルAPI などの外向き通信を阻害しない。
- 受信（incoming）はデフォルト拒否とし、tailscale0 のみ許可する。公開側（eth0 等）には何も開けない。
- 検証: tailscale 経由の接続は維持されたまま、公開 IP 側に何もポートが開いていないことを確認（`ufw status` と外部からのスキャン）。

### Phase 7: Docker の公開経路対策

Docker は iptables を直接操作し UFW をバイパスするため、追加対策が必須（LibreChat 導入前に実施）。

1. **ポートのバインド先を限定**する。Compose では `0.0.0.0` に晒さず `127.0.0.1` や Tailscale IP にバインドする。
2. **DOCKER-USER チェーン**で tailscale 以外のインターフェースからのコンテナ到達を遮断する。
   ```
   iptables -I DOCKER-USER -i ! tailscale0 -j DROP
   ```
   - このルールは再起動で消えるため、永続化（`netfilter-persistent` や UFW の `before.rules`）を行う。
- 検証: コンテナを起動した状態で、公開 IP からサービスへ到達できないことを確認する。

### Phase 8: その他の封鎖と確認

- **fail2ban**: 公開されている SSH ポートが無いため必須ではない（導入は任意）。
- **IPv6**: 使用しない場合は無効化を検討。
- **タイム同期**: `systemd-timesyncd` が有効であることを確認（Tailscale / TLS で時刻ズレ防止）。
- **パッケージ**: 使用しないサービスが起動していないかを確認。

## 検証チェックリスト

- [ ] `tailscale ssh yamatatsu@<host>` で接続できる
- [ ] 標準 `ssh yamatatsu@<host>`（ProxyCommand 設定後）でも接続できる
- [ ] 公開 IP にポートが露出していない
- [ ] root でのリモートログインができない
- [ ] パスワード認証が使えない（鍵 / tailnet ACL のみ）
- [ ] `ufw status` が `incoming: deny` かつ tailscale0 のみ許可
- [ ] Docker コンテナも公開 IP から到達できない
- [ ] unattended-upgrades が有効

## 復旧（ロックアウト時）

公開 SSH / Tailscale が塞がっても、シンVPS の **noVNC コンソール（管理画面）** から直接ログインできるため、これを最終手段とする。

- **noVNC コンソール**: sshd や Tailscale に依存せず常に使える最強の復旧経路。重宝する反面、ペーストが不便な場合がある点に留意。
- Tailscale が生きていれば、tailnet 内の別デバイスから `tailscale ssh` で入り直せる（復旧手段を複数デバイスに確保）。
- Tailscale のサービスや `tailscale0` を不用意に止めない・UFW で閉じない。
- 公開 IP 側の接続（root パスワード SSH）を完全に塞ぐ前に、必ず Tailscale SSH での復旧経路を検証しておく。
