locals {
  name    = "${var.project_name}-${var.environment}"
  enabled = var.deploy_app ? 1 : 0
  logs    = var.deploy_app ? toset(["app", "collector", "metrics"]) : toset([])
}
resource "aws_ecr_repository" "images" {
  for_each             = toset(["app", "collector"])
  name                 = "${local.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false
  image_scanning_configuration { scan_on_push = true }
}
data "aws_availability_zones" "available" { state = "available" }
resource "aws_vpc" "lab" {
  count                = local.enabled
  cidr_block           = "10.42.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
}
resource "aws_internet_gateway" "lab" {
  count  = local.enabled
  vpc_id = aws_vpc.lab[0].id
}
resource "aws_subnet" "public" {
  count             = var.deploy_app ? 2 : 0
  vpc_id            = aws_vpc.lab[0].id
  cidr_block        = cidrsubnet(aws_vpc.lab[0].cidr_block, 8, count.index)
  availability_zone = data.aws_availability_zones.available.names[count.index]
}
resource "aws_route_table" "public" {
  count  = local.enabled
  vpc_id = aws_vpc.lab[0].id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.lab[0].id
  }
}
resource "aws_route_table_association" "public" {
  count          = var.deploy_app ? 2 : 0
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public[0].id
}
resource "aws_security_group" "alb" {
  count       = local.enabled
  name_prefix = "lab-alb-"
  vpc_id      = aws_vpc.lab[0].id
}
resource "aws_security_group" "task" {
  count       = local.enabled
  name_prefix = "lab-task-"
  vpc_id      = aws_vpc.lab[0].id
}
resource "aws_vpc_security_group_ingress_rule" "client" {
  count             = local.enabled
  security_group_id = aws_security_group.alb[0].id
  cidr_ipv4         = var.allowed_client_cidr
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}
resource "aws_vpc_security_group_egress_rule" "alb" {
  count                        = local.enabled
  security_group_id            = aws_security_group.alb[0].id
  referenced_security_group_id = aws_security_group.task[0].id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}
resource "aws_vpc_security_group_ingress_rule" "app" {
  count                        = local.enabled
  security_group_id            = aws_security_group.task[0].id
  referenced_security_group_id = aws_security_group.alb[0].id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}
resource "aws_vpc_security_group_egress_rule" "https" {
  count             = local.enabled
  security_group_id = aws_security_group.task[0].id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}
resource "aws_lb" "lab" {
  count              = local.enabled
  name_prefix        = "olab-"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb[0].id]
  subnets            = aws_subnet.public[*].id
}
resource "aws_lb_target_group" "app" {
  count                = local.enabled
  name_prefix          = "olab-"
  port                 = 8000
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = aws_vpc.lab[0].id
  deregistration_delay = 30
  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}
resource "aws_lb_listener" "http" {
  count             = local.enabled
  load_balancer_arn = aws_lb.lab[0].arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app[0].arn
  }
}
resource "aws_cloudwatch_log_group" "lab" {
  for_each          = local.logs
  name              = "/${local.name}/${each.key}"
  retention_in_days = 7
}
