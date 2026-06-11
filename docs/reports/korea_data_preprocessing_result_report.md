# 한국 데이터 전처리 결과보고서

## 1. 보고서 개요

| 항목 | 내용 |
| --- | --- |
| 작성일 | 2026-06-10 |
| 대상 프로젝트 | `02_lovv_data_collect` |
| 대상 데이터 | 한국 관광 상세 Raw JSON |
| 대상 지역 | 강원도, 경상북도 |
| 처리 기준 | S3 Raw JSON 40개 파일 |
| 적재 대상 | DynamoDB `TourKoreaDomainData` |
| 실행 방식 | AWS Lambda `kr-domain-loader` 수동 실행 |

본 문서는 한국 관광 상세 데이터를 서비스에서 조회 가능한 도메인 구조로 전처리하고, DynamoDB에 적재한 결과를 정리한 결과보고서이다. 전처리 대상은 S3에 적재된 강원도와 경상북도 상세 Raw JSON이며, 음식점, 관광지, 축제, 도시 메타데이터, 방문 통계로 데이터를 분리했다.

## 2. 작업 목적

한국 관광 상세 Raw 데이터는 Tour API 원천 구조를 그대로 포함하고 있어 서비스에서 바로 조회하기 어렵다. 이번 작업의 목적은 Raw JSON을 도메인별로 분리하고, DynamoDB 조회 패턴에 맞는 key 구조로 변환하여 이후 서비스 개발과 데이터 검증에 사용할 수 있는 적재 상태를 만드는 것이다.

주요 목표는 다음과 같다.

| 목표 | 설명 | 결과 |
| --- | --- | --- |
| Raw 데이터 정리 | S3 Raw JSON을 전처리 입력으로 사용 | 완료 |
| 도메인 분리 | 음식점, 관광지, 축제, 도시 정보, 방문 통계로 분리 | 완료 |
| 컬럼 제한 | 도메인별로 필요한 컬럼만 남기도록 projection 적용 | 완료 |
| DynamoDB 적재 | `TourKoreaDomainData`에 도메인별 item 적재 | 완료 |
| 조회 기준 정리 | PK/SK와 GSI 조회 패턴 문서화 | 완료 |

## 3. 입력 데이터

전처리 입력 데이터는 다음 S3 경로를 기준으로 한다.

```text
s3://lovv-data-pipeline-dev-925273580929/raw/KR/details/20260609/*.json
```

입력 파일은 총 40개이며, 각 파일은 하나의 시군 단위 상세 Raw JSON이다.

| 구분 | 값 |
| --- | ---: |
| S3 bucket | `lovv-data-pipeline-dev-925273580929` |
| Raw prefix | `raw/KR/details/20260609/` |
| 처리 파일 수 | 40 |
| 파일 단위 | 도시 또는 시군 |
| 대표 파일 | `Andong.json` |

## 4. 전처리 방식

전처리는 `kr-domain-loader` Lambda에서 수행했다. Lambda는 S3 Raw JSON을 읽고, Python 전처리 모듈을 통해 도메인별 item을 생성한 뒤 DynamoDB에 저장한다.

처리 흐름은 다음과 같다.

```text
S3 Raw JSON
↓
kr-domain-loader Lambda 실행
↓
도시 메타데이터 생성
↓
Raw content 순회
↓
음식점 / 관광지 / 축제 / 방문 통계 분리
↓
도메인별 컬럼 projection
↓
DynamoDB PK/SK 및 GSI 속성 생성
↓
TourKoreaDomainData 적재
↓
processed/KR/domain summary 기록
```

핵심 구현 파일은 다음과 같다.

| 파일 | 역할 |
| --- | --- |
| `src/kr_details_pipeline/domain_preprocess.py` | 도메인 분류, 컬럼 projection, 품질 상태 산정 |
| `src/kr_details_pipeline/load.py` | DynamoDB item 직렬화 및 `put_item` 처리 |
| `src/kr_details_pipeline/handlers/domain_loader_handler.py` | S3 Raw JSON 기반 Lambda entrypoint |
| `docs/reports/query_usage_guide.md` | DynamoDB 조회 패턴과 PartiQL/CLI 사용 기준 |

## 5. 도메인 분류 기준

전처리 결과는 서비스 도메인에 맞춰 다음 entity type으로 분리했다.

| 원천 조건 | 분류 결과 | DynamoDB SK prefix |
| --- | --- | --- |
| `contenttypeid == 39` | 음식점 | `RESTAURANT#` |
| `contenttypeid == 12`, `14`, `28` | 관광지 | `ATTRACTION#` |
| `contenttypeid == 15` 또는 축제 배열 원천 | 축제 | `FESTIVAL#` |
| 도시 기본 정보 | 도시 메타데이터 | `METADATA#city` |
| 월별 방문 통계 | 방문 통계 | `STAT#YYYYMM` |

도메인별로 허용 컬럼만 남기도록 전처리했다. 예를 들어 음식점에는 메뉴, 영업시간, 휴무일, 주차 정보 등을 남기고, 축제에는 행사 시작일, 종료일, 행사 장소, 주최 정보 등을 남긴다.

## 6. DynamoDB 적재 구조

적재 대상 테이블은 `TourKoreaDomainData`이다.

| 항목 | 값 |
| --- | --- |
| Table | `TourKoreaDomainData` |
| Partition Key | `PK` |
| Sort Key | `SK` |
| 도시 기준 PK | `CITY#{city_name_en}` |
| 도 기준 GSI key | `PROVINCE#{province}` |

주요 key 구조는 다음과 같다.

| 데이터 유형 | PK | SK |
| --- | --- | --- |
| 도시 메타데이터 | `CITY#Andong` | `METADATA#city` |
| 음식점 | `CITY#Andong` | `RESTAURANT#{contentid}` |
| 관광지 | `CITY#Andong` | `ATTRACTION#{contentid}` |
| 축제 | `CITY#Andong` | `FESTIVAL#{contentid}` |
| 방문 통계 | `CITY#Andong` | `STAT#202501` |

조회 편의를 위해 다음 GSI를 사용한다.

| GSI | 용도 |
| --- | --- |
| GSI1 | 도시별 도메인 데이터 조회 |
| GSI2 | 도/광역 단위 도메인 데이터 조회 |
| GSI3 | entity type 기준 전체 조회 |

## 7. 실행 결과

기존 `TourKoreaDomainData`의 item을 전체 삭제한 뒤, S3 Raw JSON 40개 파일을 기준으로 재적재했다.

| 항목 | 결과 |
| --- | ---: |
| 삭제 전 item 수 | 3,814 |
| 전체 삭제 후 item 수 | 0 |
| 재적재 대상 Raw JSON | 40 |
| Lambda 실행 성공 | 40 |
| 부분 성공 | 0 |
| 실패 | 0 |
| 최종 DynamoDB item 수 | 4,334 |

모든 파일은 `kr-domain-loader` 실행 결과 `statusCode = 200`, `load_failed = 0`으로 처리되었다.

## 8. 대표 도시 산출 예시

안동 Raw JSON 기준 전처리 산출 예시는 다음과 같다.

| 산출 유형 | 건수 |
| --- | ---: |
| 도시 메타데이터 | 1 |
| 음식점 | 26 |
| 관광지 | 100 |
| 축제 | 6 |
| 방문 통계 | 12 |
| DynamoDB 적재 item | 145 |
| 검수 대상 | 0 |
| 실패 레코드 | 0 |

안동 기준으로 `PK = CITY#Andong` 아래에 음식점, 관광지, 축제, 방문 통계가 각각 별도 SK prefix로 적재되었다.

## 9. 검증 결과

검증은 로컬 테스트와 AWS 실제 적재 결과를 함께 확인했다.

| 검증 항목 | 결과 |
| --- | --- |
| Python 단위 테스트 | `18 passed` |
| DynamoDB 전체 삭제 | 완료 |
| S3 Raw 40개 파일 목록 확인 | 완료 |
| Lambda 전체 실행 | 40개 성공 |
| Lambda load 실패 | 0건 |
| 최종 DynamoDB count 확인 | 4,334건 |
| 쿼리 사용 가이드 갱신 | 완료 |
| 전처리 전용 테스트 | 완료 |
| Lambda 부분 실패 경로 테스트 | 완료 |
| Terraform 최종 검증 | `terraform plan` 결과 `No changes` |
| 도메인 테이블 GSI 상태 | `GSI1`, `GSI2`, `GSI3` 모두 `ACTIVE` |

실제 운영 검증은 수동 Lambda 실행 기준으로 진행했다. 자동 S3 event trigger는 현재 개발 단계에서는 적용하지 않았다.

## 10. 조회 예시

도시 단위 전체 조회 예시는 다음과 같다.

```bash
aws dynamodb query \
  --table-name TourKoreaDomainData \
  --key-condition-expression "PK = :pk" \
  --expression-attribute-values '{":pk":{"S":"CITY#Andong"}}' \
  --profile skn26_final --region us-east-1
```

경상북도 관광지 조회 예시는 다음과 같다.

```bash
aws dynamodb query \
  --table-name TourKoreaDomainData \
  --index-name GSI2 \
  --key-condition-expression "province_key = :province AND begins_with(domain_sort_key, :domain)" \
  --expression-attribute-values '{":province":{"S":"PROVINCE#경상북도"},":domain":{"S":"ATTRACTION#"}}' \
  --profile skn26_final --region us-east-1
```

상세 조회 패턴은 `docs/reports/query_usage_guide.md`에 정리했다.

## 11. 대응 완료 항목과 남은 이슈

아래 항목은 이전 보고서에서 남은 이슈로 분류됐던 내용 중 이번 작업에서 대응한 결과이다.

| 항목 | 대응 결과 | 상태 |
| --- | --- | --- |
| `TourKoreaData` 제거 | Terraform에서 legacy table resource와 output을 제거하고 AWS에서도 삭제 확인 | 완료 |
| 도메인 테이블 GSI 정리 | `TourKoreaDomainData`의 GSI를 도시, 도/광역, entity type 조회 기준으로 재구성 | 완료 |
| 전처리 전용 테스트 | 도메인 분류, projection allowlist, 누락 필드 failed 분리, output writer 테스트 추가 | 완료 |
| 실패 경로 검증 | `kr-domain-loader`의 DynamoDB 부분 실패 시 `statusCode = 207`과 failures payload 반환 테스트 추가 | 완료 |
| Lambda 패키징 정리 | Lambda archive에서 `tests/`, `__pycache__/` 제외 | 완료 |
| 운영 문서 정리 | README, Terraform README, 쿼리 가이드, 작업 보고서를 `TourKoreaDomainData` 기준으로 갱신 | 완료 |

현재 기준으로 남은 이슈는 다음과 같다.

| 항목 | 내용 | 대응 방향 |
| --- | --- | --- |
| 과거 Spec 정리 | 일부 과거 Spec 문서에는 초기 설계 기준의 `TourKoreaData` 명칭이 남아 있을 수 있음 | 다음 Spec 정리 작업에서 `TourKoreaDomainData` 기준으로 동기화 |
| manifest 정리 | S3 Raw ingest manifest가 실제 적재 이력을 완전히 대표하지 않음 | Raw ingest와 domain load 이력 관리 방식 확정 |
| 자동화 수준 | 현재는 수동 Lambda 실행 방식 | 개발 안정화 후 S3 event 또는 CI/CD 검토 |

## 12. 결론

한국 상세 Raw 데이터 40개 파일에 대한 전처리와 DynamoDB 적재를 완료했다. 데이터는 음식점, 관광지, 축제, 도시 메타데이터, 방문 통계로 분리되었고, `TourKoreaDomainData`에 총 4,334건이 적재되었다.

이번 작업으로 강원도와 경상북도 시군 단위 상세 데이터를 서비스 조회 구조에 맞게 사용할 수 있는 기반이 마련되었다. 또한 legacy `TourKoreaData` 제거, `TourKoreaDomainData` GSI 재구성, 전처리 전용 테스트, Lambda 부분 실패 경로 검증까지 완료되어 수동 적재 라인은 반복 실행 가능한 상태로 정리되었다. 다음 단계에서는 manifest 이력 관리와 자동 실행 방식(S3 event 또는 CI/CD)을 검토하면 된다.
