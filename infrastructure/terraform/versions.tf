terraform {
  # Terraform CLI 버전 하한과 AWS provider 의존성을 선언합니다.
  required_version = ">= 1.6.0"

  # AWS provider는 기본 제공 소스(hashicorp/aws)와 호환 버전을 사용합니다.
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# Terraform 실행 환경의 AWS 리전을 변수로 고정하고,
# CI/로컬에서 auth가 일치하도록 CLI profile을 함께 지정합니다.
provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile
}
