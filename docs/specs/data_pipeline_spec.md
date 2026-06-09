# Spec: KR 관광 데이터 파이프라인 (S3 Raw → ELT Transform → DynamoDB)

> Source: `docs/data_pipeline_prd.md` (`v0.3` 반영)
> Status: Draft for implementation planning
> Created: 2026-06-09
> Owner role: Spec Agent

## Summary

본 Spec은 `docs/data_pipeline_prd.md`의 KR(강원·경북) 데이터 파이프라인 범위를 구현하기 위한 요구사항을 정리한다.  
목표는 수집 산출물(`data/raw/final/*`, `data/city/*`, `data/visitor/*`)을 AWS 기반으로 재처리 가능한 형태로 적재하고, 검증/정규화/파생 생성 후 서비스 조회용 단일 테이블에 적재할 수 있게 하는 것이다.  
요구사항은 **AWS 설정, 코드 구조, 테스트 전략**을 함께 명시한다.

## Goals

1. `raw/KR/...` Prefix의 버전형 S3 적재를 통해 데이터 수집 결과를 멱등적으로 재처리 가능하게 한다.
2. PRD의 FR-5~16 정합 규칙에 맞춰 전처리 핵심 규칙을 코드화한다.
3. `TourKoreaData` 적재 규칙으로 City·Attraction·Festival·VisitorStatistics를 통합 조회할 수 있게 한다.
4. 멱등성, 부분 재처리, 실패 격리, 검수 큐 분류를 운영적으로 보장한다.
5. 테스트 자동화로 수량 정합, 스키마/품질 규칙, 배치 안정성, AWS 통합 동작을 검증한다.

## Phase Goals

- **Phase 0 Goal (현재 범위 우선):** Terraform 기반 IaC로 S3 Raw/Processed/Failed/Review/Quality 기반 인프라를 구축한다.
- **Phase 1 Goal (요청 반영):** 데이터를 취득(원본 파일/핸드오프)한 뒤 Raw 업로드와 `Data` 저장(`TourKoreaData`)까지 완료한다.

## Non-Goals

- JP 파이프라인 전체 구현 (향후 분리된 TASK에서 처리)
- 추천 알고리즘, 프런트엔드, 사용자 인증/결제 등 부가 도메인 기능
- S3에 이미 있는 데이터의 수동 편집 UI/대시보드 구현

## Assumptions

- 수집 산출물은 현재 디렉터리(`data/raw/final`, `data/city`, `data/visitor`)에서 선행 완료 상태라고 가정한다.
- 런타임은 Python 3.12 기준으로 작성한다.
- AWS 권한/비밀은 AWS Secrets Manager 또는 시스템 환경변수로 주입한다.
- PoC 예산 제약(NFR-4)을 벗어나지 않도록 Lambda/Batch 조합 중심으로 구성한다.

## User Flow

1. 크롤러가 산출물을 `data/...` 경로에 생성한다.
2. Upload Step에서 해당 파일이 `s3://<pipeline-bucket>/raw/KR/...` Prefix로 versioned 객체로 적재된다.
3. Transform 워커(또는 Step Functions 상태)가 Prefix 단위를 확인해 배치 manifest를 만든다.
4. Lambda `kr-transformer`가 각 객체를 읽어 schema/필드 정제/좌표·날짜/ID 표준화/신뢰도·파생 필드를 계산한다.
5. 품질 실패는 `failed/` 및 `review/<queue>` Prefix로 분기한다.
6. 성공 엔티티는 `load` 워커에서 조건부 쓰기로 `TourKoreaData`에 upsert한다.
7. 배치 메트릭(`ProcessedCount`, `FailedCount`, `ReviewQueued`, `DDBThrottle`)이 CloudWatch로 수집된다.

## Default AWS Configuration

- **IaC 도구:** Terraform (필수)
- **Region:** `us-east-1` (고정)
- AWS 리소스는 `us-east-1` 단일 리전 기준으로 설계하며, 환경별 분리는 워크스페이스(state file)로 관리한다.

## AWS Setup Requirements

### A. S3 아키텍처

- 버킷명: `lovv-data-pipeline-raw-{env}`
- 필수 Prefix
  - `raw/KR/{entity}/{yyyymmdd}/...`
  - `processed/KR/{entity}/{yyyymmdd}/...`
  - `failed/KR/{entity}/{yyyymmdd}/...`
  - `review/{queue_name}/{yyyymmdd}/...`
  - `quality/KR/{entity}/{yyyymmdd}/...`
- 설정
  - 버킷 버전 관리 활성화
  - 수명주기 정책: Raw 30~90일 이후 Glacier/IA 단계 전환(환경별 조정)
  - SSE-S3 또는 SSE-KMS(환경 정책별)
  - 최소 IAM 정책으로 읽기/쓰기 경로 제한 (`raw/`, `processed/`, `failed/`, `review/`, `quality/`)

### B. Lambda 구성

- `kr-raw-ingest` (옵션)
  - 코드: 수집 산출물을 S3 Raw Prefix로 업로드하는 래퍼(로컬 실행/CI용)
- `kr-transformer`
  - 구성 예시: 512MB, 300초, `POWERTOOLS_LOG_LEVEL=INFO`, batch size 제한
  - 트리거: S3 ObjectCreated (raw/KR/*) 또는 Step Functions 입력 manifest
  - 실패 처리: DLQ(SQS) + failed Prefix 이중 기록
- `kr-loader`
  - 역할: 검증/정규화 결과를 DynamoDB `TourKoreaData` 조건부 upsert
  - 조건부 쓰기: 핵심필드 변경/신규 시에만 갱신
- Step Functions(권장) 또는 EventBridge Rule(대체)
  - 권장: `Manifest -> Transform -> Load -> Post-Check` 상태 체인

### C. DynamoDB 저장소

- 테이블: `TourKoreaData`
- 키 전략
  - PK: `CITY#{city_name_en}`
  - SK: `ATTRACTION#{content_id}` / `FESTIVAL#{content_id}` / `METADATA#city`
- GSI
  - `GSI1`: `entity_id` 단건 조회
  - `GSI2`: `geohash_prefix` + 정렬키 범위
- 보안/운영
  - Point-in-time recovery on
  - `BillingMode`: PayPerRequest
  - TTL 정책은 품질/재처리 히스토리 정책에 맞게 단계 적용

### D. CloudWatch + 알람

- 로그:
  - 구조화 JSON 로그 (`pipeline_id`, `batch_id`, `entity_id`, `country`, `status`, `latency_ms`)
- 메트릭:
  - `ProcessedCount`, `FailedCount`, `ReviewQueued`, `DDBWriteThrottle`, `DurationMs`
- 알람:
  - `FailedCount` 임계치 초과
  - `DDBThrottle` 임계치 초과
  - DLQ 적체 수 초과

## Code Requirements

### 1) 패키지/디렉터리

- 권장 구조:
  - `backend/data_pipeline/` (또는 `crawling/pipeline/` 하위에 신설)
  - `backend/data_pipeline/config.py`
  - `backend/data_pipeline/models.py`
  - `backend/data_pipeline/raw_uploader.py`
  - `backend/data_pipeline/transform.py`
  - `backend/data_pipeline/load.py`
  - `backend/data_pipeline/cli.py`
  - `backend/data_pipeline/tests/`
- 배포 패키지: `requirements.txt`에 `boto3`, `pydantic`(또는 `pydantic-core`) 추가

### 2) 데이터 계약 및 변환 규칙 (PRD 기반)

- 입력 스키마
  - `data/raw/final/{city_en}.json`
  - `data/city/{city_en}.json`
  - `data/visitor/monthly_visitor_averages.json`
- 출력/중간 산출물
  - ELT 규칙에 따른 정규화 JSON
  - `review/*` 큐 payload
  - 품질 리포트 JSON (`quality/*`)
- 핵심 변환 규칙
  - FR-5~16 준수 (스키마/정제/ID/연락처 폴백/테마/주소·City매핑/좌표/날짜/통계-un-nest/신뢰도/파생/검수 분류)
  - `contentid` 중심 키 안정성 보장
  - 좌표(0,0)·범위 이탈은 `location_review` 분기
  - 축제 날짜는 `eventstartdate/eventenddate` → ISO + `month`, `season`, `recurrence_rule`

### 3) CLI/오케스트레이션

- `pipeline ingest` : 파일 → Raw 업로드
- `pipeline transform` : Prefix/manifest 입력 기반 일괄 변환
- `pipeline load` : 변환 결과를 `TourKoreaData` upsert
- `pipeline replay` : 실패 건/리뷰 건의 부분 재처리
- 실행 로그/메트릭이 항상 배치 단위로 남도록 설계

### 4) 오류 처리

- 일시적 실패: 지수적 backoff + DLQ 전파
- 영구 실패: failed Prefix + 리뷰 큐 전환
- 부분 실패: 배치 내 개별 엔티티 실패는 전체 실패로 확장하지 않고 라우팅

## Functional Requirements

- FR-DP-001: 동일 수집일·동일 `contentid`는 S3 versioning으로 멱등 적재 가능해야 한다.
- FR-DP-002: Transform는 FR-5~16의 모든 규칙을 적용하고 결과를 엔티티별 분기 처리해야 한다.
- FR-DP-003: City mapping과 좌표/주소 검증이 실패하면 해당 객체는 `review/location_review` 또는 `review/source_review`로 분기한다.
- FR-DP-004: `TourKoreaData` 적재는 조건부 쓰기로 idempotent upsert를 수행해야 한다.
- FR-DP-005: 실패 건은 100% `failed/KR/...` 또는 DLQ로 기록되어야 한다.
- FR-DP-006: 배치 재실행 시 동일 결과가 다시 적재되더라도 중복/덮어쓰기 부작용이 없어야 한다.
- FR-DP-007: 수량 정합(City 40, Attraction 3,709, Festival 106, VisitorStatistics 480)이 전처리 게이트를 통과할 때만 다음 단계 진행.

## Non-Functional Requirements

- NFR-1: 멱등성(중요한 S3 key, transform entity_id, DDB PK/SK 기준)
- NFR-2: 부분 재처리(국가/Prefix/City 단위)
- NFR-3: 실패 격리 및 재시도
- NFR-4: 관측성(로그·메트릭·알람)
- NFR-5: 보안(비밀관리, 개인정보 미수집, 라이선스 필드 보존)
- NFR-6: PoC 운영비 월 2만원 내외를 넘지 않는 범위에서 Lambda 우선 설계

## Testing Requirements

### Unit

- `transform.py`
  - 스키마 검증 실패 시 분류
  - 필드 정제(HTML/공백/제어문자/URL)
  - ID 규칙 변환 (`KR-{GW|GB}-{CITY_EN}`, `ATT-*`, `FEST-*`, `{city_id}-STAT-YYYYMM`)
  - 좌표/날짜 파서
  - 신뢰도 산정 함수
  - 파생 필드 생성 함수
- 테스트 대상: 최소 각 케이스 1개씩 happy/edge/error

### Integration

- ingest → raw 버킷 업로드
- transform → processed/failed 라우팅
- load → DynamoDB mock/테스트 테이블에 조건부 쓰기
- 리뷰 큐 분류(5개 큐) 동작 검증
- API 게이트웨이/Step Functions 없이 EventBridge 또는 S3 event로 Lambda 핸들러 호출 모의

### Contract

- PRD 수량 정합 검사 테스트
- FR-1~21 항목 대응 체크리스트 자동화
- DynamoDB item contract 테스트 (`PK/SK/GSI` 키 존재, 지오해시 필드)

### End-to-End

- 1개 배치 샘플 기준: ingest → transform → review 분기/ load까지 전체 실행
- 실패 시나리오: 하나의 잘못된 엔티티가 3개 중 2개 정상 결과를 영향 없이 처리하는지 확인

### Operational Safety Tests

- 재시도/부분 재처리 데모: Prefix 단위 replay
- DLQ/failed Prefix 추적성 테스트
- CloudWatch 지표 파이프라인 동작(카운터 증가, 알람 임계치 경고) 점검

## Acceptance Criteria

- AC-DP-001: `raw/KR/*` 적재 후 버전 키 생성 및 수량 검증 게이트 통과
- AC-DP-002: transform 샘플 1개 배치에서 FR-5~16 핵심 규칙 모두 통과
- AC-DP-003: `TourKoreaData`에 PK/SK가 정합된 상태로 성공 항목 적재
- AC-DP-004: 실패 항목 100%가 실패/검수 큐로 라우팅
- AC-DP-005: 재실행 시 동일 엔티티 결과의 중복 부작용이 없음
- AC-DP-006: CI에서 unit+integration 테스트가 green, 실패 시 자동 보고

## Task Breakdown

### Task (Phase 0): AWS 인프라 스택 구성

- Purpose: S3/ Lambda / DynamoDB / DLQ / CloudWatch의 최소 운영권한 기반 파이프라인 인프라를 표준화한다.
- Scope: 버킷 구조, IAM 최소권한, DynamoDB 키 설계, 실패 및 리뷰 Prefix 정책, 알람.
- Dependencies: PRD v0.1, `data_pipeline_spec.md`
- Context Budget:
  - Must read: `docs/data_pipeline_prd.md`, `docs/data_preprocessing_plan.md`(아키텍처 관점)
  - Do not read: JP 취득 상세 구현 코드
- Acceptance Criteria:
  - `us-east-1`에서 Terraform으로 버킷/테이블/함수/큐를 재생성 가능
  - 권한이 최소권한 원칙을 만족
  - Prefix와 큐 전략이 문서와 일치
- Verification:
  - 변경된 IaC 템플릿의 템플릿/보안 스캔
  - `terraform init`, `terraform validate`, `terraform fmt -check`, `terraform plan`가 `us-east-1` 타깃으로 통과
  - 샘플 배치에서 S3 이벤트가 transformer를 트리거하는지 dry-run 확인

### Task: 파이프라인 코드 구현

> Phase 1 scope(요청 반영): 데이터 취득 파일을 S3 Raw에 적재하고, Transform 후 `TourKoreaData`에 저장한다.

- Purpose: PRD FR 기반의 핵심 변환과 적재 코드를 구현해 동작 가능한 배치 파이프라인으로 만든다.
- Scope:
  - raw_uploader, transform, load, cli 구성
  - 스키마 검증, 정제, 매핑, 파생/신뢰도, 리뷰 분기
  - condition write 기반 DDB 적재
- Dependencies: AWS 인프라 스택 구성 완료, 기존 수집 산출물 포맷 확인
- Context Budget:
  - Must read: `docs/data_pipeline_prd.md`, `docs/data_preprocessing_plan.md`, 기존 수집 산출물(JSON) 샘플
  - Conditional read: `docs/04_database_design` 계열이 있으면 테이블 계약 정합 확인
- Acceptance Criteria:
  - FR-DP-001 ~ FR-DP-007 통과
  - 실패 분기/재시도/재처리 경로 코드로 구현
- Verification:
  - 변환 결과 스냅샷 비교
  - `TourKoreaData` 조건부 쓰기 동작 수동 검증

### Task (Phase 1): 테스트 자동화 및 품질 게이트

- Purpose: 파이프라인 안정성과 AWS 통합을 자동 검증하고 회귀 비용을 낮춘다.
- Scope:
  - unit/integration/contract/e2e 테스트 추가
  - CI에서 테스트 실행 워크플로우 작성
  - 커버리지 및 실패 재현성 강화
- Dependencies: 파이프라인 코드 구현
- Context Budget:
  - Must read: 현재 테스트 규칙(`crawling/*/tests`)
  - Read: CI/워크플로우 관련 스크립트가 있다면 함께
- Acceptance Criteria:
  - CI에서 단위/통합 테스트 실행이 안정적으로 green
  - 핵심 수량 정합·라우팅·적재 규칙이 자동 검증됨
- Verification:
  - `pytest` 스위트 실행
  - 인프라 smoke test(없으면 localstack 또는 mock 기반) 통과

## Risks

- 수치 정합 불일치(OI-1)로 인해 PRD 대상 수량 게이트가 과도하게 빡빡해질 수 있음
- PRD의 `City ID` 정책(국문 영문/코드 혼용) 변경 가능성
- 축제 데이터의 반복 규칙 파싱 실패로 `visit_months`·`season_tags` 품질 저하
- 라이선스/저작권 필드 누락 시 서비스 노출 불가 상태 가능성

## Open Questions

1. `raw` 적재는 완전 수동 업로드 기반으로 시작할지, S3 Event 기반 업로드를 즉시 자동화할지?
2. `LovvDataQuality`와 `TourKoreaData`를 단일 테이블로 유지할지 분리할지?
3. 리뷰 큐 처리자는 수동 운영인지 자동 worker를 둘지?
4. JP 데이터 수집/전처리/적재 범위와 우선순위를 언제 어떤 순서로 확정할지?
