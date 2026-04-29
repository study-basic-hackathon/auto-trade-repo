terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0"
    }
  }

  backend "s3" {
    region       = "ap-northeast-1"
    key          = "auto-trade-repo/prod/terraform.tfstate"
    use_lockfile = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      ManagedBy   = "terraform"
      Repository  = "auto-trade-repo"
      Environment = var.environment
    }
  }
}

# ================================================================
# network: VPC・サブネット・SG・VPC Endpoint の土台
# ================================================================

module "network" {
  source = "../../modules/network"

  project    = var.project
  aws_region = var.aws_region
}

# ================================================================
# s3: app と inference の共有ストレージ（手動アップロードの対象でもある）
# ================================================================

module "s3" {
  source = "../../modules/s3"

  project    = var.project
  aws_region = var.aws_region
}

# ================================================================
# ecr: コンテナイメージのレジストリ（CD パイプラインのデプロイ先）
# ================================================================

module "ecr" {
  source = "../../modules/ecr"

  project = var.project
}

# ================================================================
# app: IAM・ALB・ECS・CloudFront のアプリ一式
#      S3 にファイルさえあれば inference がなくても動作する
# ================================================================

module "app" {
  source = "../../modules/app"

  project            = var.project
  aws_region         = var.aws_region
  vpc_id             = module.network.vpc_id
  private_subnet_ids = module.network.private_subnet_ids
  alb_sg_id          = module.network.alb_sg_id
  ecs_sg_id          = module.network.ecs_sg_id
  s3_bucket_name     = module.s3.bucket_name
  s3_bucket_arn      = module.s3.bucket_arn
  nginx_image_uri    = var.nginx_image_uri
  api_image_uri      = var.api_image_uri
}

# ================================================================
# inference: 推論バッチ（ECS タスク定義 + 平日08:00 JST スケジューラ）
#            S3 に予測結果を書き込む。app とは独立して除外可能。
# ================================================================

module "inference" {
  source = "../../modules/inference"

  project                 = var.project
  aws_region              = var.aws_region
  cluster_arn             = module.app.cluster_arn
  task_execution_role_arn = module.app.task_execution_role_arn
  image_uri               = var.api_image_uri
  s3_bucket_name          = module.s3.bucket_name
  s3_bucket_arn           = module.s3.bucket_arn
  private_subnet_ids      = module.network.private_subnet_ids
  ecs_sg_id               = module.network.ecs_sg_id
}
