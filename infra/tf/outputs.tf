output "vpc_id" {
  description = "ID of the cluster VPC"
  value       = module.vpc.vpc_id
}

output "public_subnet_ids" {
  description = "IDs of the two public subnets"
  value       = module.vpc.public_subnets
}

output "control_plane_public_ip" {
  description = "Public IPv4 address of the kubeadm control plane"
  value       = module.k8s_cluster.control_plane_public_ip
}

output "control_plane_private_ip" {
  description = "Private IPv4 address advertised by kubeadm"
  value       = module.k8s_cluster.control_plane_private_ip
}

output "control_plane_instance_id" {
  description = "EC2 instance ID of the control plane"
  value       = module.k8s_cluster.control_plane_instance_id
}

output "control_plane_security_group_id" {
  description = "Security group modified temporarily by the bootstrap workflow"
  value       = module.k8s_cluster.control_plane_security_group_id
}

output "worker_asg_name" {
  description = "Name of the worker Auto Scaling Group"
  value       = module.k8s_cluster.worker_asg_name
}

output "ssh_command" {
  description = "Example command for connecting to the control plane"
  value       = "ssh ubuntu@${module.k8s_cluster.control_plane_public_ip}"
}