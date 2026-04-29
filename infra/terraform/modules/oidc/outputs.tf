output "github_actions_role_arn" {
  description = "GitHub Actions が Assume する IAM ロール ARN（GitHub Secrets の AWS_OIDC_ROLE_ARN に設定する）"
  value       = aws_iam_role.github_actions.arn
}
