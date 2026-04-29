variable "project" {
  description = "プロジェクト名プレフィックス"
  type        = string
}

variable "aws_region" {
  description = "AWSリージョン"
  type        = string
}

variable "cluster_arn" {
  description = "バッチを実行するECSクラスタARN（appモジュールのoutput）"
  type        = string
}

variable "task_execution_role_arn" {
  description = "ECSタスク実行ロールARN（appモジュールのoutput）"
  type        = string
}

variable "task_role_arn" {
  description = "ECSタスクロールARN（appモジュールのoutput）"
  type        = string
}

variable "image_uri" {
  description = "推論コンテナのECRイメージURI（api_image_uriと同じイメージを想定）"
  type        = string
}

variable "s3_bucket_name" {
  description = "予測結果を書き込むS3バケット名（appモジュールのoutput）"
  type        = string
}

variable "private_subnet_ids" {
  description = "タスクを配置するプライベートサブネットIDリスト（networkモジュールのoutput）"
  type        = list(string)
}

variable "ecs_sg_id" {
  description = "ECSタスクセキュリティグループID（networkモジュールのoutput）"
  type        = string
}

variable "command" {
  description = "推論コンテナの起動コマンド（実装に合わせて変更すること）"
  type        = list(string)
  default     = ["python", "-m", "inference.batch"]
}

variable "schedule_expression" {
  description = "EventBridge Schedulerのcron式（Asia/Tokyoで解釈される）"
  type        = string
  default     = "cron(0 8 ? * MON-FRI *)"
}
