output "cloudfront_domain_name" {
  description = "CloudFrontドメイン名（ブラウザアクセス用）"
  value       = aws_cloudfront_distribution.this.domain_name
}

output "cloudfront_distribution_id" {
  description = "CloudFront Distribution ID（キャッシュ無効化に使用）"
  value       = aws_cloudfront_distribution.this.id
}

output "cluster_arn" {
  description = "ECSクラスタARN（inferenceモジュールに渡す）"
  value       = aws_ecs_cluster.this.arn
}

output "task_execution_role_arn" {
  description = "ECSタスク実行ロールARN（inferenceモジュールに渡す）"
  value       = aws_iam_role.task_execution.arn
}

