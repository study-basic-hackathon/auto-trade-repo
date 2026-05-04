output "task_definition_arn" {
  description = "推論タスク定義ARN"
  value       = aws_ecs_task_definition.this.arn
}

output "schedule_name" {
  description = "EventBridge Schedulerスケジュール名"
  value       = aws_scheduler_schedule.this.name
}
