# -----------------------------------------------------------------------------
# 공통 배포 설정
# -----------------------------------------------------------------------------
variable "aws_region" {
  description = "AWS region for this pipeline."
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "AWS CLI profile used by Terraform."
  type        = string
  default     = "skn26_final"
}

variable "env" {
  description = "Deployment environment (dev/stg/prod)."
  type        = string
  default     = "dev"
}

# -----------------------------------------------------------------------------
# S3 관련 접두사: 저장 위치 규칙을 기능별로 분리합니다.
# -----------------------------------------------------------------------------
variable "bucket_base_name" {
  description = "S3 bucket name prefix for pipeline artifacts."
  type        = string
  default     = "lovv-data-pipeline"
}

variable "raw_data_prefix" {
  description = "Base prefix for KR raw input files."
  type        = string
  default     = "raw/KR"
}

variable "processed_data_prefix" {
  description = "Base prefix for processed objects."
  type        = string
  default     = "processed/KR"
}

variable "failed_data_prefix" {
  description = "Base prefix for failed objects."
  type        = string
  default     = "failed/KR"
}

variable "review_data_prefix" {
  description = "Base prefix for manual/auto review queue payloads."
  type        = string
  default     = "review"
}

variable "quality_prefix" {
  description = "Base prefix for quality report payloads."
  type        = string
  default     = "quality/KR"
}

# -----------------------------------------------------------------------------
# 데이터 저장소(DynamoDB) 구성
# -----------------------------------------------------------------------------
variable "dynamodb_table_name" {
  description = "DynamoDB table name used by service layer data."
  type        = string
  default     = "TourKoreaData"
}

# -----------------------------------------------------------------------------
# 리소스 공통 태그
# -----------------------------------------------------------------------------
variable "tags" {
  description = "Common tags for all resources."
  type        = map(string)
  default = {
    project = "lovv"
    app     = "data-pipeline"
    env     = "dev"
    managed = "terraform"
    phase   = "phase0"
  }
}
