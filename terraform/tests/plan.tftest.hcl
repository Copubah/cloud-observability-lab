mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = { names = ["us-east-1a", "us-east-1b"] }
  }
}
# Keep tests isolated from generated local deployment inputs.
variables {
  deploy_app          = false
  app_digest          = ""
  collector_digest    = ""
  allowed_client_cidr = "192.0.2.1/32"
}
run "bootstrap" {
  command = plan
  assert {
    condition     = length(aws_ecr_repository.images) == 2 && length(aws_ecs_service.lab) == 0 && length(aws_lb.lab) == 0
    error_message = "Bootstrap must create two repositories without running infrastructure."
  }
}
run "full_stack" {
  command = plan
  variables {
    deploy_app       = true
    app_digest       = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    collector_digest = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  }
  assert {
    condition     = length(aws_subnet.public) == 2 && aws_ecs_service.lab[0].desired_count == 1
    error_message = "Expected two AZ subnets and one task."
  }
  assert {
    condition     = aws_vpc_security_group_ingress_rule.app[0].from_port == 8000 && aws_vpc_security_group_ingress_rule.client[0].cidr_ipv4 == "192.0.2.1/32"
    error_message = "Application ingress must remain restricted."
  }
  assert {
    condition     = length(aws_cloudwatch_metric_alarm.errors) + length(aws_cloudwatch_metric_alarm.latency) + length(aws_cloudwatch_metric_alarm.health) == 3
    error_message = "Exactly three alarms are required."
  }
}
run "reject_missing_digests" {
  command = plan
  variables { deploy_app = true }
  expect_failures = [aws_ecs_task_definition.lab]
}
run "reject_public_ingress" {
  command = plan
  variables { allowed_client_cidr = "0.0.0.0/0" }
  expect_failures = [var.allowed_client_cidr]
}
