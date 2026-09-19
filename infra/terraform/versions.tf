terraform {
  required_version = ">= 1.3.0"
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = ">= 6.0.0"
    }
  }
}

# ~/.oci/config の DEFAULT プロファイルをそのまま使う（API キー認証）
provider "oci" {
  region = var.region
}
