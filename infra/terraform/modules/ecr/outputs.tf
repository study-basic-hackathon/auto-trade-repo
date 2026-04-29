output "nginx_repository_url" {
  description = "nginx ECRリポジトリURL（docker push 先・CD のデプロイ先）"
  value       = aws_ecr_repository.nginx.repository_url
}

output "api_repository_url" {
  description = "api ECRリポジトリURL（docker push 先・CD のデプロイ先）"
  value       = aws_ecr_repository.api.repository_url
}

output "inference_repository_url" {
  description = "inference ECRリポジトリURL（docker push 先・CD のデプロイ先）"
  value       = aws_ecr_repository.inference.repository_url
}
