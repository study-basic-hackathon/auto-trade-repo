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
variable "github_org" {
  description = "GitHubオーナー名（ユーザー名またはOrg名）"
  type        = string
}

variable "github_repo" {
  description = "GitHubリポジトリ名"
  type        = string
  default     = "auto-trade-repo"
}

variable "nginx_image_uri" {
  description = "nginx ECRイメージURI（例: xxxx.dkr.ecr.ap-northeast-1.amazonaws.com/auto-trade-repo/nginx:latest）"
  type        = string
}

variable "api_image_uri" {
  description = "api ECRイメージURI（例: xxxx.dkr.ecr.ap-northeast-1.amazonaws.com/auto-trade-repo/api:latest）"
  type        = string
}

variable "inference_image_uri" {
  description = "inference ECRイメージURI（例: xxxx.dkr.ecr.ap-northeast-1.amazonaws.com/auto-trade-repo/inference:latest）"
  type        = string
}

variable "tfstate_kms_key_id" {
  description = "tfstate バケットの KMS キー ID（暗号化されている場合のみ設定）"
  type        = string
  default     = ""
}

variable "basic_auth_username" {
  description = "CloudFront Basic認証のユーザー名"
  type        = string
  sensitive   = true
}

variable "basic_auth_password" {
  description = "CloudFront Basic認証のパスワード"
  type        = string
  sensitive   = true
}
