data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# ================================================================
# IAM（推論タスク専用ロール）
# ================================================================

resource "aws_iam_role" "task" {
  name = "${var.project}-inference-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Name = "${var.project}-inference-task-role" }
}

resource "aws_iam_role_policy" "task_s3" {
  name = "${var.project}-inference-task-s3-policy"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          var.s3_bucket_arn,
          "${var.s3_bucket_arn}/predictions/*",
          "${var.s3_bucket_arn}/models/*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = ["${var.s3_bucket_arn}/predictions/*"]
      }
    ]
  })
}

# ================================================================
# CloudWatch Logs
# ================================================================

resource "aws_cloudwatch_log_group" "this" {
  name              = "/ecs/${var.project}/inference"
  retention_in_days = 7
  tags = { Name = "/ecs/${var.project}/inference" }
}

# ================================================================
# ECS タスク定義（推論バッチ用）
# クラスタは app モジュールと共用、タスクロールは推論専用
# ================================================================

resource "aws_ecs_task_definition" "this" {
  family                   = "${var.project}-inference-task"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = var.task_execution_role_arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "inference"
      image     = var.image_uri
      essential = true
      command   = var.command
      environment = [
        { name = "S3_BUCKET_NAME", value = var.s3_bucket_name },
        { name = "AWS_REGION",     value = var.aws_region },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.this.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "inference"
        }
      }
    }
  ])

  tags = { Name = "${var.project}-inference-task" }
}

# ================================================================
# EventBridge Scheduler（平日08:00 JST に自動実行）
# ================================================================

resource "aws_iam_role" "scheduler" {
  name = "${var.project}-inference-scheduler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Name = "${var.project}-inference-scheduler-role" }
}

resource "aws_iam_role_policy" "scheduler" {
  name = "${var.project}-inference-scheduler-policy"
  role = aws_iam_role.scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["ecs:RunTask"]
        # タスク定義ファミリー内の全リビジョンを許可
        Resource = [
          "arn:aws:ecs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:task-definition/${aws_ecs_task_definition.this.family}:*"
        ]
        Condition = {
          ArnLike = { "ecs:cluster" = var.cluster_arn }
        }
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [var.task_execution_role_arn, aws_iam_role.task.arn]
      }
    ]
  })
}

resource "aws_scheduler_schedule" "this" {
  name       = "${var.project}-inference-schedule"
  group_name = "default"

  # 平日08:00 JST（市場オープン前）
  schedule_expression          = var.schedule_expression
  schedule_expression_timezone = "Asia/Tokyo"

  flexible_time_window { mode = "OFF" }

  target {
    arn      = var.cluster_arn
    role_arn = aws_iam_role.scheduler.arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.this.arn
      launch_type         = "FARGATE"
      task_count          = 1

      network_configuration {
        assign_public_ip = false
        security_groups  = [var.ecs_sg_id]
        subnets          = var.private_subnet_ids
      }
    }
  }
}
