variable "project" {
  description = "プロジェクト名プレフィックス"
  type        = string
}

variable "github_org" {
  description = "GitHubオーナー名（ユーザー名またはOrg名）"
  type        = string
}

variable "github_repo" {
  description = "GitHubリポジトリ名"
  type        = string
}

variable "tfstate_kms_key_id" {
  description = "tfstate バケットの KMS キー ID（暗号化されている場合のみ設定）"
  type        = string
  default     = ""
}
