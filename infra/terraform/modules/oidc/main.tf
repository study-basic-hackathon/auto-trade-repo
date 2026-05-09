data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.region
}

# GitHub Actions OIDC プロバイダ（AWSアカウント内に1つだけ存在すればよい）
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
  # GitHub の OIDC thumbprint（公式ドキュメント記載の値）
  thumbprint_list = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd",
  ]

  tags = { Name = "github-actions" }
}

# GitHub Actions が Assume する IAM ロール
resource "aws_iam_role" "github_actions" {
  name = "${var.project}-github-actions-ecr"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = aws_iam_openid_connect_provider.github.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          # mainブランチのpushおよびPRからのみAssumeを許可
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_org}/${var.github_repo}:*"
        }
      }
    }]
  })

  tags = { Name = "${var.project}-github-actions-ecr" }
}

# Terraform plan 用: tfstate バケットへのアクセス権限
# use_lockfile = true のためロックファイルの Put/Delete も必要
resource "aws_iam_role_policy" "tfstate_access" {
  name = "tfstate-access"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    # KMS キーが指定された場合のみ KMS ステートメントを concat で追加
    Statement = concat(
      [
        {
          Effect = "Allow"
          Action = [
            "s3:GetObject",
            "s3:PutObject",
            "s3:DeleteObject",
          ]
          Resource = "arn:aws:s3:::tfstate-${local.account_id}-ap-northeast-1-an/${var.project}/*"
        },
        {
          Effect   = "Allow"
          Action   = "s3:ListBucket"
          Resource = "arn:aws:s3:::tfstate-${local.account_id}-ap-northeast-1-an"
        },
      ],
      var.tfstate_kms_key_id != "" ? [
        {
          Effect = "Allow"
          Action = [
            "kms:Decrypt",
            "kms:GenerateDataKey",
            "kms:DescribeKey",
          ]
          Resource = "arn:aws:kms:${local.region}:${local.account_id}:key/${var.tfstate_kms_key_id}"
        }
      ] : []
    )
  })
}

# Terraform plan 用: AWSリソースの読み取り権限（ドリフト検知時に実際の状態と比較するため）
resource "aws_iam_role_policy_attachment" "readonly" {
  role       = aws_iam_role.github_actions.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# ECS サービス更新権限ポリシー（force-new-deployment + wait services-stable に必要）
resource "aws_iam_role_policy" "ecs_deploy" {
  name = "ecs-deploy"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecs:UpdateService",
          "ecs:DescribeServices",
        ]
        Resource = "arn:aws:ecs:${local.region}:${local.account_id}:service/${var.project}-cluster/${var.project}-service"
      },
    ]
  })
}

# CloudFront キャッシュ無効化権限ポリシー（フロント変更を即座に反映するため）
resource "aws_iam_role_policy" "cloudfront_invalidation" {
  name = "cloudfront-invalidation"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # distribution_id は app モジュールで生成されるため oidc モジュールからは参照できない。
        # CD 専用ロールのため、アカウント内のすべての distribution を対象としても影響範囲は限定的。
        Effect   = "Allow"
        Action   = "cloudfront:CreateInvalidation"
        Resource = "*"
      },
    ]
  })
}

# ECR push 権限ポリシー
resource "aws_iam_role_policy" "ecr_push" {
  name = "ecr-push"
  role = aws_iam_role.github_actions.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # 認証トークン取得はリソース指定不可のため * を使用
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage",
        ]
        Resource = "arn:aws:ecr:${local.region}:${local.account_id}:repository/${var.project}/*"
      },
    ]
  })
}
