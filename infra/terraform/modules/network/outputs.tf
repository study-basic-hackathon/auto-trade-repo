output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.this.id
}

output "private_subnet_ids" {
  description = "プライベートサブネットIDリスト"
  value       = [aws_subnet.private_1a.id, aws_subnet.private_1c.id]
}

output "alb_sg_id" {
  description = "ALBセキュリティグループID"
  value       = aws_security_group.alb.id
}

output "ecs_sg_id" {
  description = "ECSタスクセキュリティグループID"
  value       = aws_security_group.ecs.id
}
