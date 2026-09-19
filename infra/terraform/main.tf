locals {
  create_compartment = var.compartment_ocid == ""
  # 先頭 AD をデフォルトに（容量不足時は var.availability_domain で明示）
  availability_domain = (
    var.availability_domain != ""
    ? var.availability_domain
    : data.oci_identity_availability_domains.ads.availability_domains[0].name
  )
}

data "oci_identity_availability_domains" "ads" {
  compartment_id = var.tenancy_ocid
}

### コンパートメント（新規作成する場合）
resource "oci_identity_compartment" "main" {
  count          = local.create_compartment ? 1 : 0
  compartment_id = var.tenancy_ocid
  name           = var.compartment_name
  description    = "cloud-workplace 用"
  enable_delete  = true # terraform destroy で削除できるようにする
}

locals {
  compartment_id = local.create_compartment ? oci_identity_compartment.main[0].id : var.compartment_ocid
}

### VCN
resource "oci_core_vcn" "main" {
  compartment_id = local.compartment_id
  cidr_blocks    = ["10.0.0.0/16"]
  display_name   = "vcn-cloud-workplace"
  dns_label      = "vcnworkplace"
}

### インターネットゲートウェイ
resource "oci_core_internet_gateway" "igw" {
  compartment_id = local.compartment_id
  vcn_id         = oci_core_vcn.main.id
  display_name   = "igw-cloud-workplace"
  enabled        = true
}

### デフォルトルートテーブル（0.0.0.0/0 → IGW）
### 注意: デフォルトリソースは「作成」ではなく「管理」する。規則は全体置換なので、
###       このブロックに書いた内容がそのまま VCN のデフォルトルートテーブルになる。
resource "oci_core_default_route_table" "main" {
  manage_default_resource_id = oci_core_vcn.main.default_route_table_id
  compartment_id             = local.compartment_id
  display_name               = "default-route-table"

  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.igw.id
  }
}

### デフォルトセキュリティリスト
### ブートストラップ中は SSH(22) のみ許可。Tailscale 検証後に ingress を空にして再 apply（Phase 5）。
resource "oci_core_default_security_list" "main" {
  manage_default_resource_id = oci_core_vcn.main.default_security_list_id
  compartment_id             = local.compartment_id
  display_name               = "default-security-list"

  # ブートストラップ用。可能なら var で自 IP /32 に絞る
  ingress_security_rules {
    protocol    = "6" # TCP
    source      = "0.0.0.0/0"
    source_type = "CIDR_BLOCK"
    tcp_options {
      min = 22
      max = 22
    }
  }

  # Phase 5 完了後は上記 ingress_security_rules ブロックを削除して再 apply する

  egress_security_rules {
    protocol         = "all"
    destination      = "0.0.0.0/0"
    destination_type = "CIDR_BLOCK"
  }
}

### パブリックサブネット
resource "oci_core_subnet" "public" {
  compartment_id = local.compartment_id
  vcn_id         = oci_core_vcn.main.id
  cidr_block     = "10.0.0.0/24"
  display_name   = "public-subnet"
  dns_label      = "pub"

  route_table_id    = oci_core_default_route_table.main.manage_default_resource_id
  security_list_ids = [oci_core_default_security_list.main.manage_default_resource_id]

  # false（既定）でパブリックサブネット
  prohibit_public_ip_on_vnic = false
}

### Ubuntu aarch64 イメージの取得
data "oci_core_images" "ubuntu" {
  compartment_id   = var.tenancy_ocid
  operating_system = "Canonical Ubuntu"
  sort_by          = "TIMECREATED"
  sort_order       = "DESC"
}

locals {
  # 24.04 かつ aarch64 の最新イメージを選ぶ
  ubuntu_aarch64 = [
    for i in data.oci_core_images.ubuntu.images :
    i if can(regex("24\\.04", i.display_name)) && can(regex("aarch64", i.display_name))
  ]
  image_id = local.ubuntu_aarch64[0].id
}

### インスタンス（Ampere A1 / 2 OCPU / 12GB）
resource "oci_core_instance" "main" {
  availability_domain = local.availability_domain
  compartment_id      = local.compartment_id
  display_name        = "vps-workplace"
  shape               = "VM.Standard.A1.Flex"

  shape_config {
    ocpus         = 2
    memory_in_gbs = 12
  }

  source_details {
    source_type             = "image"
    source_id               = local.image_id
    boot_volume_size_in_gbs = 100 # Always Free 枠 200GB 内
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.public.id
    assign_public_ip = true
    hostname_label   = "vpsworkplace"
  }

  metadata = {
    ssh_authorized_keys = file(var.ssh_public_key_path)
  }
}

### シリアルコンソール接続（復旧経路）
resource "oci_core_instance_console_connection" "main" {
  instance_id = oci_core_instance.main.id
  public_key  = file(var.console_public_key_path) # RSA 鍵必須
}

### VNIC から公開 IP を引くためのデータソース
data "oci_core_vnic_attachments" "main" {
  compartment_id = local.compartment_id
  instance_id    = oci_core_instance.main.id
}

data "oci_core_vnic" "primary" {
  vnic_id = data.oci_core_vnic_attachments.main.vnic_attachments[0].vnic_id
}
