variable "project" {
  description = "プロジェクト名プレフィックス"
  type        = string
}

variable "aws_region" {
  description = "AWSリージョン"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID（networkモジュールのoutput）"
  type        = string
}

variable "private_subnet_ids" {
  description = "プライベートサブネットIDリスト（networkモジュールのoutput）"
  type        = list(string)
}

variable "alb_sg_id" {
  description = "ALBセキュリティグループID（networkモジュールのoutput）"
  type        = string
}

variable "ecs_sg_id" {
  description = "ECSタスクセキュリティグループID（networkモジュールのoutput）"
  type        = string
}

variable "s3_bucket_name" {
  description = "予測結果を読み込むS3バケット名（s3モジュールのoutput）"
  type        = string
}

variable "s3_bucket_arn" {
  description = "S3バケットARN（IAMポリシー用、s3モジュールのoutput）"
  type        = string
}

variable "nginx_image_uri" {
  description = "nginx ECRイメージURI（タグ付き）"
  type        = string
}

variable "api_image_uri" {
  description = "api ECRイメージURI（タグ付き）"
  type        = string
}
