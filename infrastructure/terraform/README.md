# Terraform Phase 0 Infrastructure (S3 / Lambda-ready IAM / DDB)

## Purpose

Phase 0 최저 구성(Infrastructure)만 배포합니다.

- S3 버킷(버전 관리, SSE, Raw 수명 주기 정책)
- 서비스 조회 테이블(`TourKoreaData`) + GSI
- Lambda 실행용 IAM Role/Policy
- CloudWatch Log Group
- DLQ/CloudWatch 알람은 현재 단계에서 제외(향후 추가 예정)

## 왜 TF_VAR_ 방식인가

Terraform은 `.env`를 자동으로 읽지 않습니다.  
`TF_VAR_<variable_name>` 환경변수로 넘기면 안전하게 변수 바인딩이 가능합니다.

예: `TF_VAR_aws_profile` → `aws_profile`

## 실행 방법 (PowerShell)

### 1) `.env` 기반 (권장)

1. `infrastructure/terraform/.env.example` → `.env`로 복사
2. 값 확인 후 `deploy.ps1` 실행

```powershell
cd infrastructure/terraform
Copy-Item .env.example .env -Force
./deploy.ps1 -Action plan
./deploy.ps1 -Action apply
```

### 2) 직접 환경변수 주입

```powershell
cd infrastructure/terraform
$env:AWS_PROFILE = "skn26_final"

$env:TF_VAR_aws_profile = "skn26_final"
$env:TF_VAR_aws_region = "us-east-1"
$env:TF_VAR_env = "dev"
$env:TF_VAR_bucket_base_name = "lovv-data-pipeline"
$env:TF_VAR_dynamodb_table_name = "TourKoreaData"
terraform init
terraform validate
terraform plan
terraform apply -auto-approve
```

### 3) 현재 생성 리소스 정리

```powershell
cd infrastructure/terraform
$env:TF_VAR_aws_profile = "skn26_final"
terraform destroy -auto-approve
```

> DLQ/알람은 Phase 0 범위 밖이므로, 추후 단계에서 추가 변수/리소스를 붙여 확장하세요.
