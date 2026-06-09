output "bucket_name" {
  # Phase 0/운영에서 생성된 파이프라인 S3 버킷 식별자
  description = "Pipeline artifact bucket name."
  value       = aws_s3_bucket.pipeline.bucket
}

output "bucket_arn" {
  # 버킷 ARN (IAM 정책 연동 또는 외부 참조에 사용).
  description = "Pipeline artifact bucket ARN."
  value       = aws_s3_bucket.pipeline.arn
}

output "dynamodb_table_name" {
  # 다음 계층(서비스/ETL)에서 참조할 테이블 이름.
  description = "Service read model table."
  value       = aws_dynamodb_table.tourkorea_data.name
}

output "dynamodb_table_arn" {
  # 테이블 ARN (권한 바인딩/감사 로그 링크용).
  description = "Service read model table ARN."
  value       = aws_dynamodb_table.tourkorea_data.arn
}

output "lambda_role_arn" {
  # 다음 단계 Lambda 생성 시 재사용할 IAM 역할 ARN.
  description = "IAM role for pipeline lambdas."
  value       = aws_iam_role.pipeline_lambda_role.arn
}
