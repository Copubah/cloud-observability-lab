output "repositories" { value = { for name, repo in aws_ecr_repository.images : name => repo.repository_url } }
output "endpoint" { value = var.deploy_app ? "http://${aws_lb.lab[0].dns_name}" : null }
output "cluster_name" { value = var.deploy_app ? aws_ecs_cluster.lab[0].name : null }
output "service_name" { value = var.deploy_app ? aws_ecs_service.lab[0].name : null }
output "log_groups" { value = { for name, group in aws_cloudwatch_log_group.lab : name => group.name } }
