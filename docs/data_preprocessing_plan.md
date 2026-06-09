# 로브 (Lovv) 데이터 전처리 계획서 초안

> 문서 버전: v0.6
> 문서 상태: 초안 (Draft)
> 작성일: 2026-06-03
> 기준 문서: 데이터 수집 계획서 v0.7
> 상세 기준: 한국 데이터 수집 계획서, 일본 데이터 수집 계획서

# 1. 문서 개요

## 1.1 목적

본 문서는 로브(Lovv)의 한국·일본 지역 추천 데이터가 수집된 이후 AWS S3에 원본을 적재하고 AWS Lambda로 전처리한 뒤 NoSQL 저장소인 Amazon DynamoDB에 서비스용 데이터를 적재하기 위한 원본 정제, 표준화, 품질 검증, 파생 데이터 생성, 적재 기준을 정의한다.

수집 계획서는 City, Attraction, Festival, VisitorStatistics 데이터를 먼저 폭넓게 취득하고 이후 검증·보정하는 방향을 가진다. 본 전처리 계획서는 그 다음 단계에서 원본 데이터의 표현 차이와 누락·중복·최신성 문제를 정리하여 서비스 사용 가능한 데이터셋으로 변환하는 데 초점을 둔다.

## 1.2 전처리 원칙

- **Raw 보존**: API 응답, HTML 추출 결과, 수동 검수 입력값은 JSON 문서로 저장한 뒤 S3 Raw 영역에 보존한다.
- **Lambda 기반 배치 처리**: S3 Raw Bucket에 일정 기간 누적된 JSON 원본을 Lambda가 배치 단위로 읽어 전처리한다.
- **DynamoDB 적재**: 서비스 조회용 데이터는 Raw와 분리하여 DynamoDB 테이블에 정규화 문서 형태로 적재한다.
- **국가별 차이 흡수**: 한국 시·군·구와 일본 시·정·촌·구의 명칭, 행정구역, 날짜, 주소 표현 차이를 공통 스키마로 매핑한다.
- **상태 기반 처리**: 모든 필드는 `collected`, `needs_review`, `missing`, `blocked` 상태를 유지하고 전처리 결과에도 상태를 전파한다.
- **출처 추적**: 정규화 값은 `source_name`, `source_url`, `collected_at`, `verified_at`, `data_confidence`와 연결한다.
- **추천 사용성 우선**: 설명, 태그, 계절성, 좌표, 운영정보는 추천·일정 생성에 바로 사용할 수 있는 형태로 가공한다.

# 2. 입력 데이터 범위

## 2.1 입력 데이터셋

| 입력 구분 | 주요 내용 | 전처리 목적 |
| --- | --- | --- |
| City Raw | 도시명, 행정구역, 좌표, 설명, 기후, 공식 사이트 | 지역 기준 엔티티 정규화 |
| Attraction Raw | 관광지명, 주소, 설명, 운영시간, 운영기간, 입장료, 좌표, 사진 | 일정 후보 데이터 정규화 |
| Festival Raw | 축제명, 개최지, 기간, 설명, 사진, 공식 링크 | 월별·계절성 추천 후보 정규화 |
| Climate Raw | 월별 평균 기온, 강수량, 계절 메모 | 여행 적합도와 계절 태그 생성 |
| Statistics Raw | 방문자 수, 관광 동향, 지역 통계 | 혼잡도·인지도 보조 지표 생성 |
| Verification Raw | 공식 사이트 확인값, 수동 검수 결과, 검수 메모 | 최신성·신뢰도 보정 |
| Korea Local Validation | `data/KR/prefectures.json`, `cities.json`, `attractions.json`, `festivals.json`, `visitor_statistics.json` | S3 Raw 적재 전 한국 실제 수집 구조와 수량 검증 |

## 2.2 기준 관계

전처리 후에도 수집 계획서의 기본 관계를 유지한다.

```text
City
 ├── Attraction
 ├── Festival
 └── VisitorStatistics
```

| 관계 | 전처리 기준 |
| --- | --- |
| `City 1:N Attraction` | 모든 관광지는 하나의 대표 City에 연결한다. 경계 지역은 주소와 좌표를 기준으로 대표 City를 결정하고 예외 메모를 남긴다. |
| `City 1:N Festival` | 모든 축제는 개최 장소 기준 City에 연결한다. 광역 개최 축제는 주 개최지와 보조 개최지를 분리한다. |
| `City 1:N VisitorStatistics` | 방문·관광 통계는 월별 또는 지역별 기준으로 City에 연결한다. 출처별 집계 단위가 다른 경우 원본 단위와 정규화 단위를 모두 남긴다. |

# 3. 전처리 아키텍처

## 3.1 구성 방향

수집 결과는 먼저 JSON 원본 파일로 직렬화해 S3 Raw Bucket에 적재한다. Raw 원본은 재사용과 재처리를 위해 일정 기간 Prefix 단위로 누적 보관하고, 보관 기간 또는 처리 기준이 충족되면 Lambda가 해당 원본 JSON 묶음을 읽어 정제·정규화·품질 검증·파생 필드 생성을 수행한 뒤 DynamoDB에 저장한다.

```text
Collector / Web Search Worker / Manual Review
↓
S3 Raw Bucket
↓
Raw 보관 기간 / 배치 기준 충족
↓
AWS Lambda Preprocessor
↓
DynamoDB Normalized Tables
↓
Search Index / RAG Dataset / Admin Review
```

## 3.2 AWS 구성 요소

| 구성 요소 | 역할 | 저장/처리 단위 |
| --- | --- | --- |
| S3 Raw Bucket | 수집 원본 누적 보존 | 국가, 출처, 엔티티 유형, 수집일 기준 객체 |
| S3 Processed Prefix | Lambda 처리 결과와 품질 리포트 보존 | 정규화 JSON, 실패 리포트, 검수 대상 목록 |
| Lambda Preprocessor | 일정 기간 누적된 Raw JSON 묶음의 스키마 검증, 필드 정제, 정규화, 중복 후보 탐지, DynamoDB 적재 | S3 Prefix 또는 배치 묶음 |
| DynamoDB | City, Attraction, Festival, VisitorStatistics, 검수 상태, 품질 메타데이터 저장 | 엔티티 단위 Item |
| CloudWatch Logs | Lambda 실행 로그와 실패 원인 기록 | 실행 요청 단위 |
| DLQ 또는 실패 Prefix | 처리 실패 이벤트 격리 | 실패 S3 객체 또는 이벤트 |

## 3.3 S3 경로 기준

| 영역 | 예시 Prefix | 내용 |
| --- | --- | --- |
| Raw | `raw/{country}/{source}/{entity_type}/{yyyy}/{mm}/{dd}/` | JSON으로 저장한 수집 원본 API 응답, HTML 추출값, 수동 입력 원본 |
| Processed | `processed/{country}/{entity_type}/{yyyy}/{mm}/{dd}/` | Lambda 전처리 결과 JSON |
| Quality | `quality/{country}/{entity_type}/{yyyy}/{mm}/{dd}/` | 품질 검증 리포트 |
| Review | `review/{queue_name}/{yyyy}/{mm}/{dd}/` | 수동 검수 대상 목록 |
| Failed | `failed/{country}/{source}/{entity_type}/{yyyy}/{mm}/{dd}/` | 처리 실패 원본과 실패 사유 |

# 4. 전처리 파이프라인

## 4.1 처리 흐름

```text
S3 Raw 데이터 적재
↓
Raw 보관 기간 / 배치 기준 확인
↓
Lambda 배치 실행
↓
스키마 검증
↓
필드 정제
↓
엔티티 정규화
↓
중복 제거 및 병합
↓
품질 점수 산정
↓
파생 필드 생성
↓
검수 대상 분류
↓
DynamoDB 적재
```

## 4.2 단계별 처리 기준

| 단계 | 처리 내용 | 산출물 |
| --- | --- | --- |
| S3 Raw 데이터 적재 | API 응답, HTML 추출값, 수동 입력값을 JSON 문서로 저장 | S3 Raw Object |
| Raw 보관 기간 / 배치 기준 확인 | 일정 기간 또는 처리 기준만큼 누적된 Raw Prefix를 전처리 대상으로 확정 | Batch Manifest |
| Lambda 배치 실행 | 확정된 S3 Prefix 또는 Manifest를 입력으로 전처리 함수 실행 | Lambda Invocation |
| 스키마 검증 | 필수 필드 존재 여부, 타입, 인코딩, 날짜 포맷 점검 | schema_validation_result |
| 필드 정제 | 공백, HTML 태그, 제어문자, 중복 문장, 깨진 URL 제거 | cleaned_fields |
| 엔티티 정규화 | 도시·관광지·축제명, 방문·관광 통계, 행정구역, 좌표, 날짜를 공통 포맷으로 변환 | normalized_entities |
| 중복 제거 및 병합 | 동일 대상의 다중 출처 데이터를 하나의 대표 엔티티로 병합 | merged_entities |
| 품질 점수 산정 | 출처 신뢰도, 최신성, 필드 충족률, 검수 여부를 점수화 | data_confidence |
| 파생 필드 생성 | 테마 태그, 월별 추천 태그, 검색 인덱스 텍스트 생성 | feature_dataset |
| 검수 대상 분류 | 누락·충돌·저작권 위험 항목을 검수 큐로 이동 | review_queue |
| DynamoDB 적재 | City, Attraction, Festival, VisitorStatistics, 품질 메타데이터를 Item 단위로 저장 | DynamoDB Item |

# 5. 공통 정규화 규칙

## 5.1 식별자 규칙

| 대상 | ID 형식 | 예시 |
| --- | --- | --- |
| 한국 City | `KR-{GW\|GB}-{CITY_EN}` | `KR-GW-GANGNEUNG` |
| 일본 City | `JP-{도도부현}-{도시명}` | `JP-ISHIKAWA-KANAZAWA` |
| 한국 Attraction | `ATT-{contentid}` (City는 `city_id`로 연결) | `ATT-126508` |
| 한국 Festival | `FEST-{contentid}` | `FEST-2762975` |
| 한국 VisitorStatistics | `{city_id}-STAT-{yyyyMM}` (전처리 파생) | `KR-GW-GANGNEUNG-STAT-202501` |
| 일본 Attraction/Festival | `{country_code}-{entity_type}-{source_or_hash}` | `JP-FEST-HASH-001` |
| 일본 VisitorStatistics | `JP-{prefecture_or_city}-STAT-{period_or_hash}` | `JP-TOKYO-STAT-202501` |

ID는 재처리 시에도 바뀌지 않아야 한다. 원본 ID가 없는 일본 공식 사이트·지자체 페이지 기반 데이터는 URL 정규화 해시를 보조 식별자로 사용한다.

## 5.2 명칭 정규화

| 구분 | 처리 기준 |
| --- | --- |
| 한국어명 | 불필요한 괄호 설명, 지역 홍보 문구, 축제 회차 표기를 분리한다. |
| 일본어 원문명 | 한자·가나 표기를 원문 필드로 보존한다. |
| 한국어 표기 | 일본 도시·관광지·축제는 서비스 표시용 한국어 표기를 별도 관리한다. |
| 검색명 | 공백 제거, 소문자화, 특수문자 제거, 별칭을 포함한 검색 키를 생성한다. |

## 5.3 주소와 행정구역 정규화

| 국가 | 처리 기준 |
| --- | --- |
| 한국 | 광역시·도, 시·군·구, 읍·면·동을 분리하고 행정구역 코드와 매핑한다. |
| 일본 | 도도부현, 시·정·촌·구를 분리하고 e-Stat 또는 Statistical LOD 기준 코드와 매핑한다. |
| 공통 | 주소가 없거나 모호한 경우 좌표, 공식 사이트 설명, 지도 링크를 보조 근거로 사용한다. |

## 5.4 좌표 정규화

- 위도·경도는 WGS84 기준 decimal degree로 저장한다.
- 좌표 범위가 국가 영역을 벗어나면 `needs_review`로 분류한다.
- City 대표 좌표와 Attraction/Festival 좌표 간 거리가 과도하게 크면 City 매핑 오류 후보로 분류한다.
- 좌표가 없는 데이터는 주소 기반 지오코딩 후보로 분류하되, 자동 지오코딩 결과는 검수 전까지 낮은 신뢰도로 둔다.

## 5.5 날짜와 기간 정규화

| 입력 유형 | 정규화 필드 |
| --- | --- |
| 단일 날짜 | `start_date`, `end_date` 동일 값 |
| 기간 | `start_date`, `end_date`, `period_text` |
| 매년 반복 축제 | `month`, `season`, `recurrence_rule`, `period_text` |
| 연도별 변동 축제 | `event_year`, `start_date`, `end_date`, `verified_at` |
| 불명확한 기간 | `period_text` 보존 후 `needs_review` |

# 6. 데이터 유형별 전처리

## 6.1 City 전처리

| 필드 | 처리 기준 |
| --- | --- |
| `city_name_ko` | 한국 도시명 또는 일본 도시의 한국어 표기를 표준명으로 저장 |
| `city_name_local` | 한국은 한국어명, 일본은 일본어 원문명을 저장 |
| `province_or_prefecture` | 국가별 행정구역 체계에 맞춰 표준화 |
| `prefecture_id` | 한국 강원·경북처럼 광역 단위가 별도 JSON에 있는 경우 상위 행정 단위 외래키로 보존 |
| `description` | 외부 원문을 그대로 저장하지 않고 내부 요약문으로 재작성 |
| `climate` | Wikipedia 취득값과 한국 기상청 또는 일본기상청(JMA) 비교 결과를 월별 기온·강수·계절 메모 구조로 분리 |
| `climate_table` | 한국 Wikipedia 기후 표 wikitext 원본을 보존하고, 전처리 단계에서 `climate` 요약과 월별 추천 지표로 분리 |
| `site_url` | 공식 관광 사이트 또는 지자체 사이트 우선 |

## 6.2 Attraction 전처리

| 필드 | 처리 기준 |
| --- | --- |
| `name` | 홍보 문구, 괄호 부가 설명, 지역 접두어를 분리하고 대표명 저장 |
| `address` | 행정구역과 상세 주소를 분리하고 City와 매핑 |
| `description` | 요약문, 검색용 본문, RAG용 문단을 분리 |
| `opening_hours` | 원문 문자열과 구조화된 영업시간을 함께 저장 |
| `opening_period` | 계절 운영 여부, 휴무 정보, 기간 원문을 분리 |
| `admission_fee` | 무료, 유료, 변동, 확인 필요 상태를 구분 |
| `photo_url` | 사용 가능 조건이 불명확하면 서비스 노출 대상에서 제외 |

## 6.3 Festival 전처리

| 필드 | 처리 기준 |
| --- | --- |
| `name` | 개최 연도·회차·지역명을 대표명과 부가 정보로 분리 |
| `period` | 연도별 날짜와 반복 월 정보를 분리 |
| `address` | 개최 장소가 여러 곳이면 주 개최지와 보조 개최지로 분리 |
| `description` | 축제 성격, 계절성, 문화 요소를 요약 태그로 추출 |
| `photo_url` | 공식 이미지 또는 사용 가능 조건이 확인된 이미지만 노출 후보로 둔다 |

# 7. 품질 검증 및 검수 큐

## 7.1 자동 검증 기준

| 검증 항목 | 기준 | 실패 시 상태 |
| --- | --- | --- |
| 필수 필드 | ID, 이름, City 매핑, 출처 URL 존재 | `missing` 또는 `needs_review` |
| City 매핑 | Attraction/Festival/VisitorStatistics가 하나의 City와 연결됨 | `needs_review` |
| 통계 기간 | 방문·관광 통계의 집계 기간과 지표명이 존재함 | `needs_review` |
| URL 유효성 | HTTP 접근 가능 또는 공식 딥링크 보존 가능 | `needs_review` |
| 좌표 범위 | 국가별 좌표 범위 안에 존재 | `needs_review` |
| 날짜 포맷 | ISO 날짜 또는 반복 규칙으로 변환 가능 | `needs_review` |
| 저작권 | 사진·설명 사용 조건 확인 가능 | `blocked` 또는 `needs_review` |
| 최신성 | 운영시간·입장료·축제 기간 확인일 존재 | `needs_review` |

## 7.2 검수 큐 분류

| 큐 | 대상 | 처리자 |
| --- | --- | --- |
| `location_review` | City 매핑 충돌, 좌표 이상치, 주소 누락 | 데이터 담당자 |
| `date_review` | 축제 기간 불명확, 연도별 일정 미확인 | 데이터 담당자 |
| `license_review` | 사진·설명문 사용 조건 불명확 | 기획/운영 담당자 |
| `content_review` | 설명 품질 낮음, 관광지 성격 모호 | 기획/운영 담당자 |
| `source_review` | 공식 출처 부재, 비공식 출처만 존재 | 데이터 담당자 |

## 7.3 신뢰도 점수

`data_confidence`는 다음 요소를 기준으로 산정한다.

| 요소 | 가중 기준 |
| --- | --- |
| 출처 공식성 | 공식 API·공식 관광 사이트·지자체 사이트를 높게 평가 |
| 최신성 | `verified_at`이 최근일수록 높게 평가 |
| 필드 충족률 | 필수 필드와 추천 핵심 필드가 채워질수록 높게 평가 |
| 출처 일치도 | 다중 출처 값이 일치할수록 높게 평가 |
| 수동 검수 | 검수 완료 항목을 높게 평가 |

# 8. 파생 데이터 생성

## 8.1 추천용 파생 필드

| 파생 필드 | 설명 |
| --- | --- |
| `theme_tags` | 자연, 음식, 역사, 문화, 휴식, 액티비티 등 추천 테마 |
| `season_tags` | 봄, 여름, 가을, 겨울, 우천 적합, 실내 중심 등 계절 태그 |
| `visit_months` | 추천 가능한 월 목록 |
| `crowding_score` | 방문자 수, 통계, 대도시 편중도 기반 혼잡 보조 점수 |
| `novelty_score` | 대도시 대비 덜 알려진 지역 추천을 위한 인지도 보조 점수 |
| `itinerary_fit` | 반나절, 1일, 1박 2일 일정 구성 적합도 |

## 8.2 RAG 및 검색용 데이터

| 산출물 | 구성 |
| --- | --- |
| City 검색 문서 | 도시 요약, 행정구역, 계절성, 대표 관광지·축제 목록 |
| Attraction 검색 문서 | 관광지 요약, 테마, 운영정보, 위치, 공식 링크 |
| Festival 검색 문서 | 축제 요약, 개최 월, 지역, 공식 링크, 최신성 상태 |
| 검색 키 | 표준명, 원문명, 별칭, 지역명, 테마 키워드 |

RAG 문서는 외부 원문을 그대로 복제하지 않고 내부 요약문과 출처 링크 중심으로 구성한다.

# 9. DynamoDB 저장 및 적재 기준

## 9.1 저장 계층

| 계층 | 저장 내용 | 용도 |
| --- | --- | --- |
| S3 Raw Bucket | 원본 응답, 추출 원문, 수집 메타데이터 | 재처리·감사·오류 추적 |
| DynamoDB Normalized Tables | City, Attraction, Festival, VisitorStatistics, 검수 상태 | 서비스 조회 |
| Search Index | 검색 문서, 임베딩 대상 텍스트, 키워드 | RAG·검색 |
| DynamoDB Review Table | 검수 큐, 검수 결과, 승인·반려 이력 | 운영 관리 |

## 9.2 DynamoDB 테이블 후보

| 테이블 | Partition Key | Sort Key | 저장 내용 |
| --- | --- | --- | --- |
| `LovvCity` | `country_code` | `city_id` | 국가별 City 정규화 데이터 |
| `LovvAttraction` | `city_id` | `attraction_id` | City에 속한 Attraction 정규화 데이터 |
| `LovvFestival` | `city_id` | `festival_id` | City에 속한 Festival 정규화 데이터 |
| `LovvVisitorStats` | `city_id` | `stat_period` | City에 연결된 월별 또는 지역별 방문·관광 통계 |
| `LovvDataQuality` | `entity_id` | `checked_at` | 품질 검증 결과, 신뢰도, 실패 사유 |
| `LovvReviewQueue` | `queue_name` | `entity_id` | 수동 검수 대상과 처리 상태 |

## 9.3 Item 공통 속성

| 속성 | 설명 |
| --- | --- |
| `entity_id` | City, Attraction, Festival, VisitorStatistics의 안정 식별자 |
| `entity_type` | `city`, `attraction`, `festival`, `visitor_statistics` |
| `country_code` | `KR` 또는 `JP` |
| `source_name` | 원본 출처명 |
| `source_url` | 원본 또는 공식 확인 URL |
| `s3_raw_uri` | 재처리를 위한 S3 Raw 객체 경로 |
| `normalized_payload` | 서비스 조회용 정규화 데이터 |
| `quality_status` | `collected`, `needs_review`, `missing`, `blocked` |
| `data_confidence` | 출처, 최신성, 필드 충족률 기반 신뢰도 |
| `collected_at` | 원본 수집 시각 |
| `processed_at` | Lambda 처리 시각 |
| `verified_at` | 공식 확인 또는 수동 검수 시각 |

## 9.4 적재 조건

| 대상 | 최소 적재 조건 |
| --- | --- |
| City | 표준 ID, 도시명, 국가, 행정구역, 출처 URL |
| Attraction | 표준 ID, 이름, City 매핑, 출처 URL, 주소 또는 좌표 |
| Festival | 표준 ID, 이름, City 매핑, 기간 원문 또는 개최 월, 출처 URL |
| VisitorStatistics | 표준 ID, City 매핑, 집계 기간, 지표명, 수치, 출처 URL |
| 검색 문서 | 내부 요약문, 출처 링크, 최신성 상태 |
| 서비스 노출 | 필수 필드 충족, 저작권 위험 없음, `blocked` 아님 |

## 9.5 Lambda 적재 실패 처리

| 실패 유형 | 처리 |
| --- | --- |
| 스키마 오류 | DynamoDB에 적재하지 않고 S3 `failed/` Prefix와 품질 리포트에 사유 기록 |
| 필수 필드 누락 | `LovvReviewQueue`에 검수 대상으로 등록 |
| DynamoDB 조건부 쓰기 실패 | 기존 Item과 충돌 여부를 확인하고 변경 이력 후보로 분류 |
| Lambda 타임아웃 | 처리 단위를 더 작은 S3 객체 또는 배치로 나누어 재시도 |
| 일시적 AWS 오류 | 재시도 후 실패 이벤트를 DLQ 또는 실패 Prefix에 보존 |

# 10. 운영 및 재처리 정책

| 항목 | 정책 |
| --- | --- |
| 재처리 주기 | City 기본 정보는 정기 배치, 운영시간·입장료·축제 기간은 최신성 상태에 따라 우선 재처리 |
| 부분 재처리 | 특정 S3 Prefix, 특정 출처, 특정 국가, 특정 City 단위로 Lambda 재실행 가능해야 함 |
| Raw 보관 기간 | 원본 JSON은 재사용 가능한 기간 동안 S3 Raw Bucket에 보관하고, 보관 기간 만료 후에는 보존 정책에 따라 Glacier 전환 또는 삭제를 검토 |
| 배치 전처리 기준 | 보관 기간 경과, Prefix 단위 수집 완료, 수동 검수 마감 등 운영 기준 중 하나가 충족되면 Lambda 전처리를 실행 |
| 변경 감지 | 동일 원본 ID의 핵심 필드가 바뀌면 DynamoDB 변경 이력 후보를 남김 |
| 롤백 | DynamoDB 적재 실패 시 기존 승인 Item을 유지하고 신규 결과는 실패 Prefix에 격리 |
| 감사 추적 | S3 Raw URI, Lambda 실행 시각, Web Search Worker 확인, 수동 검수 결과를 모두 이력화 |

# 11. 법적·운영 유의사항

- Wikipedia 기반 설명은 출처와 원문 링크를 남기되 서비스 본문에는 내부 요약문을 사용한다.
- TourAPI, JNTO, JTA, 지자체 관광 사이트의 이용 조건과 출처 표기 조건을 보존한다.
- 사진은 사용 가능 조건이 확인된 경우에만 서비스 노출 후보로 둔다.
- 상업 플랫폼의 숙박·맛집 데이터는 직접 저장하지 않고 검색 딥링크 또는 사용자 이동 경로로 처리한다.
- 운영시간, 입장료, 축제 기간은 변경 가능성이 높으므로 서비스 응답에는 확인일 기준 문구를 연결한다.

# 12. 산출물

| 산출물 | 설명 |
| --- | --- |
| `city_normalized` | 국가별 도시 표준 엔티티 |
| `attraction_normalized` | City와 연결된 관광지 표준 엔티티 |
| `festival_normalized` | City와 연결된 축제 표준 엔티티 |
| `visitor_statistics_normalized` | City와 연결된 방문·관광 통계 보조 지표 |
| `data_quality_report` | 누락, 충돌, 최신성, 저작권 위험 리포트 |
| `review_queue` | 수동 검수 대상 목록 |
| `rag_documents` | 추천 Agent와 검색용 내부 요약 문서 |
| `feature_dataset` | 테마, 계절성, 혼잡도, 일정 적합도 파생 필드 |
| `s3_raw_manifest` | DynamoDB Item과 연결되는 S3 Raw 객체 목록 |
| `lambda_processing_log` | Lambda 실행 결과, 실패 사유, 재처리 대상 기록 |

# 13. 본 문서 반영 이력

| 버전 | 날짜 | 작성자 | 변경 내용 |
| --- | --- | --- | --- |
| v0.1 | 2026-06-03 | LLM 파트 | 데이터 수집 계획서를 기반으로 전처리 계획서 초안 작성 |
| v0.2 | 2026-06-03 | LLM 파트 | S3 Raw 적재, Lambda 전처리, DynamoDB 적재 아키텍처 반영 |
| v0.3 | 2026-06-06 | LLM 파트 | S3 Raw 누적 보관 후 Lambda 배치 전처리 및 DynamoDB 적재 흐름 반영 |
| v0.4 | 2026-06-06 | LLM 파트 | 한국 강원·경북 실제 수집 산출물, `KR-{도_코드}-{CITY_EN}` ID 형식, `climate_table` 전처리 기준 반영 |
| v0.5 | 2026-06-07 | LLM 파트 | VisitorStatistics 관계, 정규화 산출물, DynamoDB 후보 테이블, 적재 조건 보완 |
| v0.6 | 2026-06-09 | 조동휘 | `tour-api-korea` 코드 대조로 한국 식별자 규칙 정정: City `KR-{GW\|GB}-*`, Attraction `ATT-{contentid}`, Festival `FEST-{contentid}`. 상세는 `kr_preprocessing_detail_design.md` v0.3·`kr_preprocessing_code_based_design.md` 참조 |
