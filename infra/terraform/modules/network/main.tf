data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

# ================================================================
# VPC
# ================================================================

resource "aws_vpc" "this" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = { Name = "${var.project}-vpc" }
}

# ================================================================
# プライベートサブネット（Internet Gateway・NAT Gateway なし）
# ================================================================

resource "aws_subnet" "private_1a" {
  vpc_id            = aws_vpc.this.id
  cidr_block        = "10.0.1.0/24"
  availability_zone = "${var.aws_region}a"

  tags = { Name = "${var.project}-private-1a" }
}

resource "aws_subnet" "private_1c" {
  vpc_id            = aws_vpc.this.id
  cidr_block        = "10.0.2.0/24"
  availability_zone = "${var.aws_region}c"

  tags = { Name = "${var.project}-private-1c" }
}

# 両サブネット共通のルートテーブル（S3 Gateway Endpoint を紐付け）
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id

  tags = { Name = "${var.project}-rtb-private" }
}

resource "aws_route_table_association" "private_1a" {
  subnet_id      = aws_subnet.private_1a.id
  route_table_id = aws_route_table.private.id
}

resource "aws_route_table_association" "private_1c" {
  subnet_id      = aws_subnet.private_1c.id
  route_table_id = aws_route_table.private.id
}

# ================================================================
# セキュリティグループ（ALB・ECS・VPC Endpoint）
# ================================================================

resource "aws_security_group" "vpc_endpoint" {
  name        = "${var.project}-vpc-endpoint-sg"
  description = "Interface VPC Endpoint用"
  vpc_id      = aws_vpc.this.id

  tags = { Name = "${var.project}-vpc-endpoint-sg" }
}

resource "aws_security_group" "ecs" {
  name        = "${var.project}-ecs-sg"
  description = "ECS Fargate Task用"
  vpc_id      = aws_vpc.this.id

  tags = { Name = "${var.project}-ecs-sg" }
}

resource "aws_security_group" "alb" {
  name        = "${var.project}-alb-sg"
  description = "Internal ALB用"
  vpc_id      = aws_vpc.this.id

  tags = { Name = "${var.project}-alb-sg" }
}

# VPC Endpoint: ECS からの HTTPS のみ受け付ける
resource "aws_vpc_security_group_ingress_rule" "vpc_endpoint_from_ecs" {
  security_group_id            = aws_security_group.vpc_endpoint.id
  referenced_security_group_id = aws_security_group.ecs.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
  description                  = "ECSタスクからのHTTPS"
}

# ALB: CloudFront VPC Origin からの HTTP のみ受け付ける
resource "aws_vpc_security_group_ingress_rule" "alb_from_cloudfront" {
  security_group_id = aws_security_group.alb.id
  prefix_list_id    = data.aws_ec2_managed_prefix_list.cloudfront.id
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  description       = "CloudFront VPC OriginからのHTTP"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_ecs" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.ecs.id
  ip_protocol                  = "tcp"
  from_port                    = 80
  to_port                      = 80
  description                  = "ECSタスクへのHTTP転送"
}

# ECS: ALB からの HTTP のみ受け付け、アウトバウンドは全許可（VPC Endpoint 経由）
resource "aws_vpc_security_group_ingress_rule" "ecs_from_alb" {
  security_group_id            = aws_security_group.ecs.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 80
  to_port                      = 80
  description                  = "ALBからのHTTP"
}

resource "aws_vpc_security_group_egress_rule" "ecs_to_all" {
  security_group_id = aws_security_group.ecs.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "-1"
  description       = "全アウトバウンド許可（VPC Endpoint・S3 Gateway 経由）"
}

# ================================================================
# VPC Endpoints（プライベートサブネットから AWS サービスへアクセス）
# ================================================================

# S3 Gateway Endpoint（無料・ルートテーブルにルートを追加）
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  tags = { Name = "${var.project}-vpce-s3" }
}

# ECR API（docker pull 時の API 呼び出し）
resource "aws_vpc_endpoint" "ecr_api" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.ecr.api"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private_1a.id, aws_subnet.private_1c.id]
  security_group_ids  = [aws_security_group.vpc_endpoint.id]
  private_dns_enabled = true

  tags = { Name = "${var.project}-vpce-ecr-api" }
}

# ECR DKR（docker pull 時のレイヤー取得）
resource "aws_vpc_endpoint" "ecr_dkr" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.ecr.dkr"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private_1a.id, aws_subnet.private_1c.id]
  security_group_ids  = [aws_security_group.vpc_endpoint.id]
  private_dns_enabled = true

  tags = { Name = "${var.project}-vpce-ecr-dkr" }
}

# CloudWatch Logs（コンテナログ送信）
resource "aws_vpc_endpoint" "logs" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${var.aws_region}.logs"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private_1a.id, aws_subnet.private_1c.id]
  security_group_ids  = [aws_security_group.vpc_endpoint.id]
  private_dns_enabled = true

  tags = { Name = "${var.project}-vpce-logs" }
}
