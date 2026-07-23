output "module_vpc_id" {
  description = "ID of the VPC created by the VPC module"
  value       = try(module.polyai_service_vpc[0].vpc_id, null)
}

output "module_public_subnet_ids" {
  description = "IDs of public subnets created by the VPC module"
  value       = try(module.polyai_service_vpc[0].public_subnets, [])
}
output "discovered_ubuntu_ami_id" {
  description = "Most recent Ubuntu 24.04 AMI discovered in the selected region"
  value       = data.aws_ami.ubuntu.id
}