data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "this" {
  bucket           = "${var.project}-${data.aws_caller_identity.current.account_id}-${var.aws_region}-an"
  bucket_namespace = "account-regional"

  tags = { Name = "${var.project}-${data.aws_caller_identity.current.account_id}-${var.aws_region}-an" }
}

resource "aws_s3_bucket_public_access_block" "this" {
  bucket                  = aws_s3_bucket.this.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  bucket = aws_s3_bucket.this.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# モデルファイルや予測結果の履歴を保持するためバージョニングを有効化
resource "aws_s3_bucket_versioning" "this" {
  bucket = aws_s3_bucket.this.id

  versioning_configuration {
    status = "Enabled"
  }
}
