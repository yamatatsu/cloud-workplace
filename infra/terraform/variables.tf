variable "region" {
  description = "OCI リージョン（例: ap-tokyo-1）"
  type        = string
}

variable "tenancy_ocid" {
  description = "テナンシ OCID（~/.oci/config の tenancy と同じ）"
  type        = string
}

variable "compartment_name" {
  type    = string
  default = "cloud-workplace"
}

variable "compartment_ocid" {
  description = "既存コンパートメントを使う場合のみ指定。空なら新規作成"
  type        = string
  default     = ""
}

variable "availability_domain" {
  description = "空なら一覧の先頭 AD を使う（容量不足時は明示指定）"
  type        = string
  default     = ""
}

variable "ssh_public_key_path" {
  type    = string
  default = "~/.ssh/oci_boot.pub"
}

variable "console_public_key_path" {
  description = "シリアルコンソール接続用。RSA 鍵必須"
  type        = string
  default     = "~/.ssh/oci_console_rsa.pub"
}
