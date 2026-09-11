locals {
  assume_task = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_iam_role" "execution" {
  count              = local.enabled
  name               = "${local.name}-execution"
  assume_role_policy = local.assume_task
}
resource "aws_iam_role" "task" {
  count              = local.enabled
  name               = "${local.name}-task"
  assume_role_policy = local.assume_task
}
resource "aws_iam_role_policy" "execution" {
  count = local.enabled
  role  = aws_iam_role.execution[0].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
    { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"], Resource = [for repo in aws_ecr_repository.images : repo.arn] },
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = [for key in ["app", "collector"] : "${aws_cloudwatch_log_group.lab[key].arn}:*"] }
  ] })
}
resource "aws_iam_role_policy" "task" {
  count = local.enabled
  role  = aws_iam_role.task[0].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"], Resource = "*" },
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.lab["metrics"].arn}:*" }
  ] })
}
