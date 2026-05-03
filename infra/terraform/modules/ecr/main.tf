locals {
  lifecycle_policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "直近5イメージのみ保持"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 5
      }
      action = { type = "expire" }
    }]
  })
}

resource "aws_ecr_repository" "nginx" {
  name                 = "${var.project}/nginx"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration { scan_on_push = true }

  tags = { Name = "${var.project}/nginx" }
}

resource "aws_ecr_repository" "api" {
  name                 = "${var.project}/api"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration { scan_on_push = true }

  tags = { Name = "${var.project}/api" }
}

resource "aws_ecr_repository" "inference" {
  name                 = "${var.project}/inference"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration { scan_on_push = true }

  tags = { Name = "${var.project}/inference" }
}

resource "aws_ecr_lifecycle_policy" "nginx" {
  repository = aws_ecr_repository.nginx.name
  policy     = local.lifecycle_policy
}

resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name
  policy     = local.lifecycle_policy
}

resource "aws_ecr_lifecycle_policy" "inference" {
  repository = aws_ecr_repository.inference.name
  policy     = local.lifecycle_policy
}
