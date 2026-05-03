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
