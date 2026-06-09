# 로브 (Lovv) 데이터 파이프라인 PRD (한정)

> 문서 버전: v0.3
> 문서 상태: 초안 (Draft)
> 작성일: 2026-06-09 (v0.3 정책 반영: 2026-06-09)
> 작성자: 조동휘
> 범위 한정: **데이터 파이프라인(취득 → 전처리 → 적재)**. 제품 전체 PRD 아님
> 입력 문서: `03_data_collect_plan`(취득), `08_data_preprocessing`(전처리), `04_database_design`(적재 타깃)
> **취득 라인(Extract)**: `Gloveman/tour-api-korea` (main) **git repo를 참조·재사용**한다(재구현 금지). 본 PRD의 구현 대상은 그 산출물 이후의 Load(Raw)·Transform·Load(Service)다.

> **[v0.3 업데이트]** 취득 단계는 이미 `tour-api-korea` repo에 구현되어 있으므로, 본 PRD는 취득을 **외부 업스트림 의존(참조)**으로 두고 그 산출물을 핸드오프 계약(§3.5)으로 받는다. 신규 코드 작업 범위는 §1.3 "구현 대상"으로 한정한다.

# 1. 개요

## 1.1 목적

본 문서는 로브(Lovv) 추천 서비스의 **데이터 파이프라인**(수집된 한국 관광 데이터를 서비스 조회용 데이터로 변환·적재하는 과정)에 대한 제품 요구사항을 정의한다. 제품 전체 PRD가 아니라, 데이터 소싱·ELT 전처리·DB 적재에 한정한다. 제품 비전·사용자·기능 요구사항은 `00_project_plan`·`01_requirements`·`02_service_flow`를 따른다.

## 1.2 배경

로브는 한일 여행자에게 혼잡한 유명지 대신 소도시를 추천하는 대화형 서비스다. 추천 품질은 도시·관광지·축제·방문통계 데이터의 정확성·최신성·정규화 수준에 직접 의존한다. 현재 한국(강원·경북) 데이터는 `tour-api-korea` 샘플 코드로 수집·정규화되어 도시별 JSON으로 산출되며, 이를 서비스 조회용 저장소로 변환·적재하는 파이프라인이 필요하다.

## 1.3 범위

| 구분 | 내용 |
| --- | --- |
| **참조(재사용)** | **취득(Extract)**: `tour-api-korea` repo의 수집·정규화 코드와 산출물. 본 PRD에서 재구현하지 않고 핸드오프 계약(§3.5)으로 소비 |
| **구현 대상(신규)** | ① Load(Raw): repo 산출물 → S3 Raw, ② Transform: 검증·정제·정규화·파생·검수분류(Lambda), ③ Load(Service): DynamoDB 단일 테이블 적재 |
| 제외 | 취득 코드 재작성, 일본(JP) 상세 규칙(향후), 추천 알고리즘·Agent 로직, 사용자·일정 트랜잭션 데이터(MySQL 소관), 프론트엔드/API 구현 |
| 대상 수량 | City 40, Attraction 3,709, Festival 106, 상세 3,815, VisitorStatistics 40×12=480 |

## 1.4 용어

| 용어 | 정의 |
| --- | --- |
| Raw | 수집 원본/정규화본 JSON. S3 Raw 영역에 보존 |
| ELT | Extract → Load(Raw to S3) → Transform(in-place) |
| Transform | 스키마검증→정제→정규화→병합→신뢰도→파생→검수분류 |
| 적재 타깃 | 서비스 조회용 DynamoDB 단일 테이블(`TourKoreaData`) + S3 vector index |

# 2. 목표와 성공 지표

## 2.1 목표

1. 수집 산출물(`data/raw/final/*`, `data/city/*`, `data/visitor/*`)을 손실 없이 S3 Raw에 적재해 재처리·감사 추적을 보장한다.
2. 국가·출처별 표현 차이를 공통 스키마로 정규화하고 추천에 바로 쓸 수 있는 파생 필드(테마·계절·혼잡도)를 생성한다.
3. 누락·충돌·저작권 위험을 검수 큐로 분리해 서비스 노출 데이터의 품질을 보장한다.
4. 멱등·부분 재처리·실패 격리가 가능한 배치 파이프라인을 PoC 예산(주당 약 2만 원 내외) 안에서 운영한다.

## 2.2 성공 지표 (수용 기준 연계)

| 지표 | 목표 |
| --- | --- |
| 수량 정합 | 적재 City 40 / Attraction 3,709 / Festival 106 / VisitorStatistics 480 일치 |
| City 매핑률 | 모든 Attraction·Festival이 유효 `city_id`에 매핑 (미매핑 0, 또는 전량 `location_review`) |
| 좌표 유효율 | `(0.0,0.0)`·KR BBOX 이탈 0건(또는 전량 검수 분기) |
| 테마 매핑률 | 적재 대상의 `theme != None` 100%(미매핑은 `content_review`) |
| 멱등성 | 동일 배치 재실행 시 동일 `entity_id`·동일 결과(`processed_at`만 갱신) |
| 재처리 격리 | 실패 객체가 `failed/` Prefix·`LovvDataQuality`에 100% 기록 |

# 3. 취득 라인 참조 (업스트림 git repo)

## 3.1 참조 원칙

취득(Extract)은 **`Gloveman/tour-api-korea` (main) repo를 정본·재사용**한다. 본 PRD·구현은 취득 코드를 복제하거나 재작성하지 않으며, repo가 산출한 데이터 파일을 **읽기 전용 입력**으로 받는다. 취득 로직 변경이 필요하면 본 repo가 아니라 **`tour-api-korea`에 PR**로 반영한다.

| 항목 | 값 |
| --- | --- |
| 저장소 | `https://github.com/Gloveman/tour-api-korea` (main) |
| 책임 | 강원·경북 40도시 City·Attraction·Festival·VisitorStatistics 수집·정규화 |
| 인터페이스 | 아래 산출 파일(§3.5 핸드오프 계약) |
| 변경 경로 | 취득 규칙 변경은 `tour-api-korea`에 반영, 본 파이프라인은 계약만 의존 |

## 3.2 참조 repo가 제공하는 단계·산출물 (재구현 금지)

| 단계 | 스크립트(참조용) | 산출물 |
| --- | --- | --- |
| 리스트 | `scrape_list.py` | `data/raw/list/*` |
| 그룹화 | `group_lists_by_city.py` | `data/raw/list_by_city/*` (40도시) |
| 테마 | `filter_existing_lists.py` | 테마 매핑 + 축제 오버라이드 46건 |
| 상세 | `scrape_details.py` | `data/raw/detail/{contentid}.json` |
| 병합 | `merge_to_final.py` | `data/raw/final/{city_en}.json` |
| 통계 | `scrape_and_aggregate_visitor.py` | final 임베드 + `data/visitor/monthly_visitor_averages.json` |
| 정규화 | `normalize_details.py` | `data/city/{city_en}.json` |

> 위 스크립트·필드 동작은 참조 정보일 뿐이며, 본 파이프라인이 의존하는 것은 §3.5의 **산출 파일 계약**이다. 상세는 `kr_preprocessing_code_based_design.md` v0.2 참조.

## 3.3 데이터 소스 (repo가 호출, 본 파이프라인은 직접 호출 안 함)

| 소스 | 용도 | 비고 |
| --- | --- | --- |
| TourAPI 4.0 KorService2 | 관광지·축제 리스트·상세 | repo가 호출. 키·로테이션·Fail-Fast는 repo 책임 |
| TourAPI DataLabService (`locgoRegnVisitrDDList`) | 월별 방문통계 | `touDivCd` 1/2/3, 1달 구간 |
| Excel `korea_region_latitude_longitude.xlsx` | City 좌표 | 없으면 centroid 폴백 |
| (향후) Wikipedia/Wikidata, 기상청 | City 설명·기후 보강 | repo·전처리 양쪽 미구현, 보강 과제 |

> 본 파이프라인이 TourAPI를 직접 호출하는 경우는 **경계 재취득(누락·갱신 보강)**에 한하며, 그때도 repo의 키·오류 정책(쿼터 `0022` 로테이션, 영구 오류 10·11·12·30·31·32 Fail-Fast)을 따른다.

## 3.4 착수 전 확정 필요 결정 (Pre-req)

데이터 계약을 좌우하므로 코드 착수 전에 문서에서 확정한다(코드에서 고치면 재작업 큼).

| 결정 | 옵션 | 권고 |
| --- | --- | --- |
| 테마 수집 범위 | 확장(오버라이드/후속 보강) vs 정본만 수집 | **1차는 정본(`lclsSystm3 or cat3`) 수집만 수행** |
| City 취득 언어 | City 영문/한국어 혼재 또는 로컬화 우선 | **취득 시 City 영어명(`city_name_en`) 우선 적용, 최종 표시 정책은 T 단계에서 결정** |
| City ID 도 코드 | `KR-GW/GB-*`(현 코드) vs `KR-42/47-*`(숫자) | 하나로 확정 후 매핑 규칙 명시 (OI-2) |
| 일본(JP) 대응 범위 | KR-only 마감 후 JP 확대 | **일단 KR-only 진행, JP 수집 전략은 추후 별도 확정** |
| 적재 테이블 | `TourKoreaData` 단일 테이블(04) vs `LovvCity` 후보(전처리) | **04 DB 설계를 정본**으로 통일 (OI-4) |
| tel 처리 방식 | 코드에서의 즉시 폴백 vs 별도 보정 JSON 병합 | **코드 미구현, `contact_overrides.json` 별도 적재 후 병합** |
| 수량 정본 | 4,911(분류) vs 3,709(적재) | **3,709 정본** + 재집계 검증 (OI-1) |

## 3.5 핸드오프 계약 (repo 산출 파일 → 파이프라인 입력)

본 파이프라인의 입력 정본은 다음 파일이다. repo는 이 구조를 보장하고, 파이프라인은 이 구조에만 의존한다.

| 입력 파일 | 내용 | 소비 단계 |
| --- | --- | --- |
| `data/raw/final/{city_en}.json` | 리스트+`detail`(common/intro)+`visitor_statistics` 임베드 | Attraction·Festival·VisitorStatistics 추출 |
| `data/city/{city_en}.json` | 정규화 City·Attraction·Festival·metadata | City 메타 및 정규화 참조 |
| `data/visitor/monthly_visitor_averages.json` | 방문통계 전역 요약 | 통계 교차 검증 |
| `data/contact_overrides.json` (선택) | 연락처 보정 후보(`city_id`, `content_id`, `phone_number`, `source`, `collected_at`) | FR-8 병합 단계 |

계약 불변식(파이프라인이 가정하는 것): 관광지/축제는 `contentid` 안정 키 보유, City는 `KR-{GW|GB}-{CITY_EN}` 형식, 축제 기간은 `detail.intro.eventstartdate/eventenddate`(YYYYMMDD), 방문통계는 `monthly_statistics[]` 12개월·`touDivCd` 1/2/3 합산 일평균. 전화번호는 `contact_overrides.json` 병합 여부에 따라 최종 결정. **계약이 깨지면(필드명·구조 변경) repo와 본 PRD §3.5를 동시에 갱신한다.**

# 4. 기능 요구사항 (FR)

## 4.1 Load(Raw): 참조 repo 산출물 핸드오프

- **FR-1** 참조 repo(`tour-api-korea`)의 산출 파일(§3.5)을 가져와 S3 Raw Prefix(`raw/KR/...`)에 적재한다. 취득 로직은 호출하지 않고 **산출물만 핸드오프**한다.
- **FR-2** 데이터 정본은 S3로 두고 GitHub에는 코드·문서·소량 설정만 둔다(15MB 임계값 규칙).
- **FR-3** 동일 수집일·`contentid` 객체는 덮어쓰지 않고 버전 Prefix로 누적한다(멱등 적재).
- **FR-4** 적재 전 §3.5 핸드오프 계약 검증(파일 존재·구조·수량 City 40 / Attraction 3,709 / Festival 106)을 통과해야 적재를 확정한다. 계약 위반 시 파이프라인을 중단하고 repo 측 보정을 요청한다.

## 4.2 Transform (Lambda 배치)

- **FR-5 스키마 검증**: 필수 필드·타입·날짜(YYYYMMDD)·좌표 파싱 가능 여부를 점검하고, 실패 객체는 `failed/` 격리한다.
- **FR-6 필드 정제**: HTML 태그·제어문자·공백·깨진 URL 제거, 100% 결측 필드 제거. 결측을 `false`로 치환하지 않고 생략/`null` 보존한다.
- **FR-7 식별자 정규화**: City `KR-{GW|GB}-{CITY_EN}`, Attraction `ATT-{contentid}`, Festival `FEST-{contentid}`, VisitorStatistics `{city_id}-STAT-{yyyyMM}`. `contentid`를 안정 키로 재처리 시 불변.
- **FR-8 연락처 보강**: `tel`은 코드에서 미구현. 파이프라인은 `contact_overrides.json`(선택, 별도 업로드)에서 전화번호를 병합하여 최종 산출에 반영한다.
- **FR-9 테마 검증**: `lclsSystm3` 또는 `cat3` 기반 정본 테마만 수집·검증한다. 오버라이드(축제 46건)는 다음 단계에서 반영 범위를 재검토한다.
- **FR-10 주소·City 매핑**: 주소 분해 후 법정동 코드 기준 City 매핑. 미매핑은 `location_review`.
- **FR-11 좌표 정규화**: `mapx/mapy` → WGS84 decimal + Geohash(12자리)·Geohash prefix(5자리). KR BBOX 이탈·`(0.0,0.0)`은 `location_review`.
- **FR-12 날짜 정규화**: 축제 `eventstartdate/eventenddate`(YYYYMMDD) → ISO, `month`·`season` 파생, 반복 축제 `recurrence_rule`.
- **FR-13 방문통계 unnest**: final 임베드 `visitor_statistics.monthly_statistics[]` 12건을 도시별 독립 `VisitorStatistics` 아이템으로 분리하고 표준명(`local`/`outsider`/`foreigner`)으로 매핑한다.
- **FR-14 신뢰도 산정**: 출처 공식성·최신성·필드 충족률·다중출처 일치도·검수 여부로 `data_confidence`를 산정한다(코드의 문자열 상태와 병행 보존).
- **FR-15 파생 필드**: `theme_tags`·`season_tags`·`visit_months`·`crowding_score`(방문통계 기반)·`novelty_score` 생성.
- **FR-16 검수 분류**: `location_review`·`date_review`·`license_review`·`content_review`·`source_review` 큐로 분류한다.

## 4.3 Load (서비스 적재)

- **FR-17** 정규화 결과를 서비스 조회용 단일 테이블 `TourKoreaData`에 적재한다. PK `CITY#{city_name_en}`, SK `ATTRACTION#{content_id}`/`FESTIVAL#{content_id}`/`METADATA`(도시 메타).
- **FR-18** 가변 소개 정보를 `details` 맵으로 감싸 다형성 모델로 적재하고, `geohash`·`geohash_prefix`를 포함한다.
- **FR-19** 공간 검색을 위해 GSI(`GSI1` content_id 단건 조회, `GSI2` geohash_prefix/geohash 범위)를 구성한다.
- **FR-20** 적재는 조건부 쓰기로 핵심 필드 변경·신규일 때만 갱신하고, 충돌은 변경 이력 후보로 기록한다.
- **FR-21** 서비스 노출 대상은 필수 필드 충족·저작권 위험 없음·`blocked` 아님을 만족해야 한다.

# 5. 비기능 요구사항 (NFR)

| ID | 항목 | 요구 |
| --- | --- | --- |
| NFR-1 | 멱등성 | Load(Raw) S3 Key, Transform `entity_id`, Load(Service) PK+SK 기준 재실행 안전 |
| NFR-2 | 부분 재처리 | 특정 S3 Prefix·출처·City 단위 Lambda 재실행 가능. 규칙 변경 시 원본 재수집 없이 Transform만 재실행 |
| NFR-3 | 실패 처리 | 스키마 오류→`failed/`+품질 리포트, 필수 누락→`ReviewQueue`, 타임아웃→배치 분할, 일시 오류→재시도 후 DLQ |
| NFR-4 | 비용 | 상시 인프라 대신 이벤트 기반 배치 Lambda(512MB/300s/배치 500). PoC 주당 약 2만 원 내외 |
| NFR-5 | 관측성 | `ProcessedCount`·`FailedCount`·`ReviewQueued`·`DDBThrottle`·`Duration` 지표 + 구조화 로그 |
| NFR-6 | 보안 | TourAPI 키는 `.env`/시크릿으로 관리, Git 커밋 금지. 개인정보 없음(공공 관광 데이터) |
| NFR-7 | 법적 | 공공누리 유형(`cpyrhtDivCd`) 보존, 사진은 사용 조건 확인 시만 노출. Wikipedia 출처 표기, 본문은 내부 요약 |
| NFR-8 | 최신성 | 운영시간·입장료·축제 기간은 확인일 문구 연결. 변동 큰 필드는 신뢰도 하향 |

# 6. 데이터 계약 (참조)

입력(Raw)·정규화(Transform 출력)·적재(DynamoDB Item) 스키마는 `kr_preprocessing_detail_design.md` §12, 코드 산출물 실구조는 `kr_preprocessing_code_based_design.md` §2·§4를 정본으로 참조한다. 적재 타깃 단일 테이블·GSI·아이템 예시는 `04_database_design/nosql_schema_design.md` §6을 정본으로 한다.

# 7. 마일스톤

| 단계 | 산출물 | 완료 기준 |
| --- | --- | --- |
| M0 결정 확정 | §3.4 Pre-req 항목 합의 | City ID·테마·언어·JP범위·테이블·tel·수량 정본 확정 |
| M1 Raw 적재 | repo 산출물 → S3 Raw + 계약 검증 | FR-1~4, 핸드오프 계약·수량 정합 통과 |
| M2 Transform 코어 | 정규화·매핑·좌표·날짜 | FR-5~13, 단위테스트 통과 |
| M3 품질·파생 | 신뢰도·파생·검수 큐 | FR-14~16, 검수 큐 분류 동작 |
| M4 서비스 적재 | DynamoDB 단일 테이블·GSI | FR-17~21, 공간 쿼리 검증 |
| M5 운영화 | 멱등·재처리·관측성 | NFR-1~5 충족, 부분 재처리 데모 |

# 8. 리스크 · 미해결 (Open Issues)

| ID | 항목 | 상태 | 신뢰도 |
| --- | --- | --- | --- |
| OI-1 | 테마 합계 4,911 ↔ 적재 3,709 차이(1,202건) | 정본 3,709 기준 확정, 정합성 검증 계속 진행 | 확인 필요 |
| OI-2 | City ID 도 코드 정책(영문 `GW`/`GB` vs 숫자 `42`/`47`) | 미정 — 정책 결정 필요 | 확인 필요 |
| OI-3 | `tel` 처리 정책 | **별도 보정 JSON 방식으로 일단 확정** | 확인 필요(운영 설계) |
| OI-4 | City 명칭 표기(영문취득 후 T에서 정규화/표기) | T 단계 정책 결정 대기 | 사용자 추가 확인 필요 |
| OI-5 | JP(일본) 수집·전처리·적재 수집 전략 | 별도 scope 확정 전 | 확인 필요 |
| OI-6 | 적재 테이블 명칭 정합(`TourKoreaData` 단일 테이블 ↔ 전처리 문서 `LovvCity` 등 후보) | DB 설계(04)를 정본으로 통일 권고 | 중 |

# 9. 참조 문서

- **취득 코드(참조·재사용)**: `Gloveman/tour-api-korea` (main)
- 취득 계획: `docs/03_data_collect_plan/korea_data_acquisition_plan_updated.md` v0.3, `korea_acquisition_plan_corrections.md` v0.1
- 전처리: `docs/08_data_preprocessing/data_preprocessing_plan.md` v0.6, `kr_preprocessing_detail_design.md` v0.3, `kr_preprocessing_code_based_design.md` v0.2
- 적재: `docs/04_database_design/04_database_design.md` v0.5, `nosql_schema_design.md`

# 10. 변경 이력

| 버전 | 날짜 | 작성자 | 변경 내용 |
| --- | --- | --- | --- |
| v0.1 | 2026-06-09 | 조동휘 | 데이터 파이프라인 한정 PRD 초안 작성: 취득(03)·전처리(08)·적재(04) 종합. 목표·성공지표·FR(21)·NFR(8)·마일스톤·리스크·수용기준 정의. 범위 KR(강원·경북), JP 제외 |
| v0.2 | 2026-06-09 | 조동휘 | 취득 라인을 `tour-api-korea` git repo 참조·재사용으로 재구성(재구현 금지). 업스트림 의존·핸드오프 계약(§3.5)·착수 전 확정 결정(§3.4) 신설, 구현 대상을 Load(Raw)·Transform·Load(Service)로 한정, FR-1을 산출물 핸드오프로 재정의, M0 결정 확정 마일스톤 추가 |
| v0.3 | 2026-06-09 | 조동휘 | PRD 미해결 항목 재정리: 테마 정본 우선 수집, City 영어취득 우선, tel는 코드 미구현 후 `contact_overrides.json` 병합, JP 범위/방향은 T 단계 결정 보류, M0 기준 항목 보강 |
