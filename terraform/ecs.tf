resource "aws_ecs_cluster" "lab" {
  count = local.enabled
  name  = local.name
  setting {
    name  = "containerInsights"
    value = "enhanced"
  }
}
resource "aws_ecs_task_definition" "lab" {
  count                    = local.enabled
  family                   = local.name
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.execution[0].arn
  task_role_arn            = aws_iam_role.task[0].arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  container_definitions = jsonencode([
    {
      name                   = "collector", image = "${aws_ecr_repository.images["collector"].repository_url}@${var.collector_digest}"
      essential              = true, memory = 256, cpu = 128
      readonlyRootFilesystem = true
      environment = [
        { name = "AWS_REGION", value = var.aws_region },
        { name = "EMF_LOG_GROUP", value = aws_cloudwatch_log_group.lab["metrics"].name },
        { name = "LAB_ENVIRONMENT", value = var.environment },
        { name = "GOMEMLIMIT", value = "128MiB" }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options   = { awslogs-group = aws_cloudwatch_log_group.lab["collector"].name, awslogs-region = var.aws_region, awslogs-stream-prefix = "ecs" }
      }
    },
    {
      name        = "app", image = "${aws_ecr_repository.images["app"].repository_url}@${var.app_digest}"
      essential   = true, memory = 768, cpu = 384, user = "10001:10001"
      stopTimeout = 30
      # SQLite uses the image-owned writable directory; data is disposable.
      readonlyRootFilesystem = false
      portMappings           = [{ containerPort = 8000, protocol = "tcp" }]
      dependsOn              = [{ containerName = "collector", condition = "START" }]
      healthCheck = {
        command  = ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).close()"]
        interval = 10, timeout = 3, retries = 3, startPeriod = 15
      }
      environment = [for key, value in {
        DATABASE_PATH               = "/app/data/lab.db"
        OTEL_SERVICE_NAME           = "cloud-observability-lab"
        OTEL_RESOURCE_ATTRIBUTES    = "deployment.environment.name=${var.environment}"
        OTEL_TRACES_EXPORTER        = "otlp"
        OTEL_METRICS_EXPORTER       = "otlp"
        OTEL_LOGS_EXPORTER          = "console"
        OTEL_EXPORTER_OTLP_PROTOCOL = "http/protobuf"
        OTEL_EXPORTER_OTLP_ENDPOINT = "http://127.0.0.1:4318"
        OTEL_TRACES_SAMPLER         = "parentbased_always_on"
        OTEL_METRIC_EXPORT_INTERVAL = "10000"
        SIMULATE_DB_LATENCY         = tostring(var.simulate_db_latency)
        SIMULATE_ERRORS             = tostring(var.simulate_errors)
      } : { name = key, value = value }]
      logConfiguration = {
        logDriver = "awslogs"
        options   = { awslogs-group = aws_cloudwatch_log_group.lab["app"].name, awslogs-region = var.aws_region, awslogs-stream-prefix = "ecs" }
      }
    }
  ])
  lifecycle {
    precondition {
      condition     = var.app_digest != "" && var.collector_digest != ""
      error_message = "Publish both ECR images and supply their digests before setting deploy_app=true."
    }
  }
}
resource "aws_ecs_service" "lab" {
  count                             = local.enabled
  name                              = local.name
  cluster                           = aws_ecs_cluster.lab[0].id
  task_definition                   = aws_ecs_task_definition.lab[0].arn
  desired_count                     = 1
  launch_type                       = "FARGATE"
  platform_version                  = "1.4.0"
  health_check_grace_period_seconds = 60
  # Avoid two independent SQLite writers during a rollout; accept demo downtime.
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.task[0].id]
    assign_public_ip = true
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.app[0].arn
    container_name   = "app"
    container_port   = 8000
  }
  depends_on = [aws_lb_listener.http, aws_iam_role_policy.execution, aws_iam_role_policy.task, aws_route_table_association.public]
}
