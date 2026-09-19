output "instance_id" {
  value = oci_core_instance.main.id
}

output "public_ip" {
  value = data.oci_core_vnic.primary.public_ip_address
}

output "availability_domain" {
  value = local.availability_domain
}

output "console_connection_string" {
  value     = oci_core_instance_console_connection.main.connection_string
  sensitive = true
}
