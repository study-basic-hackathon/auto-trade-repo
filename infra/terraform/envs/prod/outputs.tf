output "cloudfront_domain_name" {
  description = "CloudFrontドメイン名（ブラウザアクセス用）"
  value       = module.app.cloudfront_domain_name
}

output "cloudfront_distribution_id" {
  description = "CloudFront Distribution ID（キャッシュ無効化に使用）"
  value       = module.app.cloudfront_distribution_id
}

output "nginx_ecr_repository_url" {
  description = "nginx ECRリポジトリURL（docker push 先）"
  value       = module.ecr.nginx_repository_url
}

output "api_ecr_repository_url" {
  description = "api ECRリポジトリURL（docker push 先）"
  value       = module.ecr.api_repository_url
}

output "inference_ecr_repository_url" {
  description = "inference ECRリポジトリURL（docker push 先）"
  value       = module.ecr.inference_repository_url
}

output "github_actions_role_arn" {
  description = "GitHub Actions OIDC ロール ARN（GitHub Secrets の AWS_OIDC_ROLE_ARN に設定する）"
  value       = module.oidc.github_actions_role_arn
}
