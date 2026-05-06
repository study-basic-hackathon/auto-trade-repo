# ================================================================
# IAM（タスク実行ロール・タスクロール）
# ================================================================

resource "aws_iam_role" "task_execution" {
  name = "${var.project}-ecs-task-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Name = "${var.project}-ecs-task-execution-role" }
}

resource "aws_iam_role_policy_attachment" "task_execution" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "task" {
  name = "${var.project}-ecs-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Name = "${var.project}-ecs-task-role" }
}

resource "aws_iam_role_policy" "task_s3" {
  name = "${var.project}-ecs-task-s3-policy"
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
          "${var.s3_bucket_arn}/metrics/*",
          "${var.s3_bucket_arn}/explanations/*",
        ]
      }
    ]
  })
}

# ================================================================
# CloudWatch Logs
# ================================================================

resource "aws_cloudwatch_log_group" "nginx" {
  name              = "/ecs/${var.project}/nginx"
  retention_in_days = 7
  tags = { Name = "/ecs/${var.project}/nginx" }
}

resource "aws_cloudwatch_log_group" "fastapi" {
  name              = "/ecs/${var.project}/fastapi"
  retention_in_days = 7
  tags = { Name = "/ecs/${var.project}/fastapi" }
}

# ================================================================
# ALB（Internal）
# ================================================================

resource "aws_lb" "this" {
  name               = "${var.project}-alb"
  internal           = true
  load_balancer_type = "application"
  security_groups    = [var.alb_sg_id]
  subnets            = var.private_subnet_ids

  tags = { Name = "${var.project}-alb" }
}

resource "aws_lb_target_group" "this" {
  name        = "${var.project}-tg"
  port        = 80
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/api/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 60
    timeout             = 5
    matcher             = "200"
  }

  tags = { Name = "${var.project}-tg" }
}

resource "aws_lb_listener" "this" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this.arn
  }
}

# ================================================================
# ECS（クラスタ・タスク定義・サービス）
# ================================================================

resource "aws_ecs_cluster" "this" {
  name = "${var.project}-cluster"

  setting {
    name  = "containerInsights"
    value = "disabled"
  }

  tags = { Name = "${var.project}-cluster" }
}

resource "aws_ecs_task_definition" "this" {
  family                   = "${var.project}-task"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "nginx"
      image     = var.nginx_image_uri
      essential = true
      portMappings = [{ containerPort = 80, protocol = "tcp" }]
      environment = [
        { name = "API_HOST", value = "localhost" },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.nginx.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "nginx"
        }
      }
    },
    {
      name      = "fastapi"
      image     = var.api_image_uri
      essential = true
      portMappings = [{ containerPort = 8080, protocol = "tcp" }]
      environment = [
        { name = "S3_BUCKET_NAME", value = var.s3_bucket_name },
        { name = "AWS_REGION",     value = var.aws_region },
        { name = "DEFAULT_TICKER", value = "n225" },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.fastapi.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "fastapi"
        }
      }
    }
  ])

  tags = { Name = "${var.project}-task" }
}

resource "aws_ecs_service" "this" {
  name            = "${var.project}-service"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.ecs_sg_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.this.arn
    container_name   = "nginx"
    container_port   = 80
  }

  depends_on = [aws_lb_listener.this]

  tags = { Name = "${var.project}-service" }
}

# ================================================================
# CloudFront Functions（Basic認証）
# ================================================================

resource "aws_cloudfront_function" "basic_auth" {
  name    = "${var.project}-basic-auth"
  runtime = "cloudfront-js-2.0"
  publish = true

  code = <<-JS
    function handler(event) {
      var request = event.request;
      var headers = request.headers;
      var expectedUser = '${var.basic_auth_username}';
      var expectedPass = '${var.basic_auth_password}';
      var authHeader = headers.authorization;
      if (authHeader) {
        var encoded = authHeader.value.split(' ')[1];
        if (encoded) {
          var decoded = atob(encoded);
          var sep = decoded.indexOf(':');
          if (sep !== -1) {
            var user = decoded.slice(0, sep);
            var pass = decoded.slice(sep + 1);
            if (user === expectedUser && pass === expectedPass) {
              return request;
            }
          }
        }
      }
      return {
        statusCode: 401,
        statusDescription: 'Unauthorized',
        headers: {
          'www-authenticate': { value: 'Basic realm="Restricted"' }
        }
      };
    }
  JS
}

# ================================================================
# CloudFront（VPC Origin → Internal ALB）
# ================================================================

resource "aws_cloudfront_vpc_origin" "this" {
  vpc_origin_endpoint_config {
    name                   = "${var.project}-vpc-origin"
    arn                    = aws_lb.this.arn
    http_port              = 80
    https_port             = 443
    origin_protocol_policy = "http-only"

    origin_ssl_protocols {
      items    = ["TLSv1.2"]
      quantity = 1
    }
  }

  tags = { Name = "${var.project}-vpc-origin" }
}

resource "aws_cloudfront_distribution" "this" {
  enabled         = true
  is_ipv6_enabled = true
  comment         = "${var.project} distribution"
  price_class     = "PriceClass_200"

  origin {
    domain_name = aws_lb.this.dns_name
    origin_id   = "alb-vpc-origin"

    vpc_origin_config {
      vpc_origin_id = aws_cloudfront_vpc_origin.this.id
    }
  }

  # デフォルト: 静的アセット（キャッシュあり）
  default_cache_behavior {
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    target_origin_id       = "alb-vpc-origin"
    viewer_protocol_policy = "redirect-to-https"
    cache_policy_id        = "658327ea-f89d-4fab-a63d-7e88639e58f6" # Managed-CachingOptimized
    compress               = true

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.basic_auth.arn
    }
  }

  # /api/*: APIレスポンス（キャッシュなし）
  ordered_cache_behavior {
    path_pattern             = "/api/*"
    allowed_methods          = ["GET", "HEAD", "OPTIONS"]
    cached_methods           = ["GET", "HEAD"]
    target_origin_id         = "alb-vpc-origin"
    viewer_protocol_policy   = "redirect-to-https"
    cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # Managed-CachingDisabled
    origin_request_policy_id = "216adef6-5c7f-47e4-b989-5492eafa07d3" # Managed-AllViewer
    compress                 = false

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.basic_auth.arn
    }
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = { Name = "${var.project}-distribution" }
}
