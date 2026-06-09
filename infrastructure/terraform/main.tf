# -----------------------------------------------------------------------------
# Runtime context
# -----------------------------------------------------------------------------
# 현재 AWS 계정 ID를 읽어오기 위해 caller identity를 조회해
# 리소스 명명/ARN 구성 시 일관된 식별값(account_id)을 사용합니다.
data "aws_caller_identity" "current" {}

# -----------------------------------------------------------------------------
# 공통 유틸리티 값
# -----------------------------------------------------------------------------
# 버킷명은 환경명과 계정 ID를 결합해 고유하게 생성합니다.
# Lambda 이름은 stage 간 구분을 위해 로컬 맵으로 관리합니다.
# 태그는 사용자 태그에 env를 덮어써서 환경 정합성을 보장합니다.
locals {
  bucket_name = "${var.bucket_base_name}-${var.env}-${data.aws_caller_identity.current.account_id}"
  lambda_names = {
    raw_ingest   = "kr-raw-ingest"
    transformer  = "kr-transformer"
    loader       = "kr-loader"
  }
  base_tags = merge(var.tags, { env = var.env })
}

resource "aws_s3_bucket" "pipeline" {
  # 수집된 원천/가공 데이터가 들어갈 파이프라인 저장소입니다.
  bucket        = local.bucket_name
  force_destroy = false

  tags = merge(local.base_tags, { Name = local.bucket_name })
}

resource "aws_s3_bucket_versioning" "pipeline" {
  # 객체 버전관리를 활성화해 실수/변경 이력 복원이 가능하도록 합니다.
  bucket = aws_s3_bucket.pipeline.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "pipeline" {
  # 저장 시 기본 SSE(AES256) 적용으로 저장 데이터 기초 보호를 강화합니다.
  bucket = aws_s3_bucket.pipeline.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "pipeline" {
  # 퍼블릭 접근이 차단되도록 모든 퍼블릭-차단 스위치를 ON으로 설정합니다.
  bucket                  = aws_s3_bucket.pipeline.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "pipeline" {
  # 원천 데이터 보관 정책:
  # 30일 후 STANDARD_IA, 60일 후 GLACIER로 이동합니다.
  bucket = aws_s3_bucket.pipeline.id

  rule {
    id     = "raw-cold-storage"
    status = "Enabled"

    filter {
      prefix = "${var.raw_data_prefix}/"
    }

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 60
      storage_class = "GLACIER"
    }
  }
}

resource "aws_dynamodb_table" "tourkorea_data" {
  # 서비스 데이터 조회/분석을 위한 단일 테이블 설계.
  # 기본 키(PK, SK) + GSI2개로 조회 패턴을 분리합니다.
  name           = var.dynamodb_table_name
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "PK"
  range_key      = "SK"
  stream_enabled = false

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  attribute {
    name = "entity_id"
    type = "S"
  }

  attribute {
    name = "geohash_prefix"
    type = "S"
  }

  global_secondary_index {
    name            = "GSI1"
    hash_key        = "entity_id"
    projection_type  = "ALL"
  }

  global_secondary_index {
    name            = "GSI2"
    hash_key        = "geohash_prefix"
    range_key       = "SK"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = merge(local.base_tags, { Name = var.dynamodb_table_name })
}

resource "aws_iam_role" "pipeline_lambda_role" {
  # Lambda 실행 역할. Lambda 서비스가 AssumeRole로 사용합니다.
  name = "lovv-data-pipeline-lambda-${var.env}"

  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = merge(local.base_tags, { Name = "lovv-data-pipeline-lambda-role-${var.env}" })
}

resource "aws_iam_role_policy" "pipeline_lambda_policy" {
  # Lambda 기능에 필요한 최소 권한을 인라인으로 제한합니다.
  # 현재 단계에서는 DynamoDB, S3, CloudWatch Logs만 허용합니다.
  name = "lovv-data-pipeline-lambda-policy-${var.env}"
  role = aws_iam_role.pipeline_lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:GetItem",
          "dynamodb:DeleteItem",
          "dynamodb:Query"
        ]
        Resource = aws_dynamodb_table.tourkorea_data.arn
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:DescribeTable"
        ]
        Resource = aws_dynamodb_table.tourkorea_data.arn
      },
      {
        Effect   = "Allow"
        Action = [
          "s3:ListBucket",
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject"
        ]
        Resource = [
          aws_s3_bucket.pipeline.arn,
          "${aws_s3_bucket.pipeline.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "lambda_raw_ingest" {
  # raw_ingest Lambda 런타임 로그. 보관 기간은 14일.
  name              = "/aws/lambda/${local.lambda_names.raw_ingest}"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "lambda_transformer" {
  # transformer Lambda 런타임 로그. 보관 기간은 14일.
  name              = "/aws/lambda/${local.lambda_names.transformer}"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "lambda_loader" {
  # loader Lambda 런타임 로그. 보관 기간은 14일.
  name              = "/aws/lambda/${local.lambda_names.loader}"
  retention_in_days = 14
}
