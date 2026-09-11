resource "aws_cloudwatch_metric_alarm" "errors" {
  count               = local.enabled
  alarm_name          = "${local.name}-high-5xx"
  alarm_description   = "Target 5xx >5% with >=10 requests/min; excludes ALB-generated failures."
  comparison_operator = "GreaterThanThreshold"
  threshold           = 5
  evaluation_periods  = 5
  datapoints_to_alarm = 3
  treat_missing_data  = "notBreaching"
  metric_query {
    id          = "rate"
    expression  = "IF(requests >= 10, 100 * FILL(errors, 0) / requests, 0)"
    label       = "Target 5xx percent"
    return_data = true
  }
  dynamic "metric_query" {
    for_each = { errors = "HTTPCode_Target_5XX_Count", requests = "RequestCount" }
    content {
      id = metric_query.key
      metric {
        metric_name = metric_query.value
        namespace   = "AWS/ApplicationELB"
        period      = 60
        stat        = "Sum"
        dimensions  = { LoadBalancer = aws_lb.lab[0].arn_suffix, TargetGroup = aws_lb_target_group.app[0].arn_suffix }
      }
    }
  }
}
resource "aws_cloudwatch_metric_alarm" "latency" {
  count                                 = local.enabled
  alarm_name                            = "${local.name}-high-p99"
  alarm_description                     = "ALB target header latency p99 >2s; deliberate /slow traffic can trigger this."
  namespace                             = "AWS/ApplicationELB"
  metric_name                           = "TargetResponseTime"
  dimensions                            = { LoadBalancer = aws_lb.lab[0].arn_suffix, TargetGroup = aws_lb_target_group.app[0].arn_suffix }
  extended_statistic                    = "p99"
  period                                = 60
  comparison_operator                   = "GreaterThanThreshold"
  threshold                             = 2
  evaluation_periods                    = 5
  datapoints_to_alarm                   = 3
  treat_missing_data                    = "notBreaching"
  evaluate_low_sample_count_percentiles = "evaluate"
}
resource "aws_cloudwatch_metric_alarm" "health" {
  count               = local.enabled
  alarm_name          = "${local.name}-unhealthy-task"
  alarm_description   = "Unhealthy app containers (one per task); absent/stopped tasks are not detected."
  namespace           = "ECS/ContainerInsights"
  metric_name         = "UnHealthyContainerHealthStatus"
  dimensions          = { ClusterName = aws_ecs_cluster.lab[0].name, ServiceName = local.name, ContainerName = "app" }
  statistic           = "Maximum"
  period              = 60
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  evaluation_periods  = 5
  datapoints_to_alarm = 3
  treat_missing_data  = "missing"
}
