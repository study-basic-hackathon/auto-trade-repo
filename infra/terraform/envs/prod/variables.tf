variable "aws_region" {
  description = "AWSリージョン"
  type        = string
  default     = "ap-northeast-1"
}

variable "project" {
  description = "プロジェクト名プレフィックス"
  type        = string
  default     = "auto-trade-repo"
}

variable "environment" {
  description = "環境名"
  type        = string
  default     = "prod"
}

# ECRリポジトリを作成してからイメージをpushし、そのURIを設定する
# 初回デプロイ手順:
#   1. nginx_image_uri / api_image_uri を仮URI（例: nginx:latest）で terraform apply
#   2. 出力された ECR URL にイメージをpush
#   3. 正しいURIに更新して再度 terraform apply
variable "nginx_image_uri" {
  description = "nginx ECRイメージURI（例: xxxx.dkr.ecr.ap-northeast-1.amazonaws.com/auto-trade-repo/nginx:latest）"
  type        = string
}

variable "api_image_uri" {
  description = "api ECRイメージURI（例: xxxx.dkr.ecr.ap-northeast-1.amazonaws.com/auto-trade-repo/api:latest）"
  type        = string
}
