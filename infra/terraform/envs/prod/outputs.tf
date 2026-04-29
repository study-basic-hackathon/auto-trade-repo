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
  value       = module.app.nginx_ecr_repository_url
}

output "api_ecr_repository_url" {
  description = "api ECRリポジトリURL（docker push 先）"
  value       = module.app.api_ecr_repository_url
}
