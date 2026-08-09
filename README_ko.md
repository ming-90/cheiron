# Cheiron — ClinicalTrials.gov 질의-시각화 에이전트

Cheiron은 자연어로 입력한 임상시험 질문을 실제 [ClinicalTrials.gov Data API](https://clinicaltrials.gov/data-api/api) 데이터에 근거한 프론트엔드 렌더링용 시각화 JSON으로 변환하는 AI 에이전트입니다.

LLM은 제한된 분석 계획과 시각화 설계에만 사용합니다. 연구 검색, 통계 계산 또는 차트 데이터 생성을 LLM에 맡기지 않습니다. API 요청 컴파일, 페이지네이션, 정규화, 필터링, 고유 NCT 집계, 인용 연결 및 출력 검증은 결정론적인 Python 코드가 수행합니다.

내장 웹 애플리케이션은 반환된 JSON을 ECharts로 렌더링하며, 모든 에이전트 실행과 ClinicalTrials.gov 요청을 확인할 수 있는 모니터링 화면도 제공합니다.

## 주요 기능

- 한국어 및 영어 자연어 질문 지원
- 미리 정의된 엄격한 `AnalysisPlan`을 이용한 OpenAI 툴콜링
- `query`와 동일한 깊이에 위치하는 선택적 구조화 필드
- ClinicalTrials.gov `/studies` 페이지네이션, 재시도, NCT ID 중복 제거
- 결정론적 시계열·분포·비교·순위·네트워크 집계
- 막대, 가로 막대, 그룹 막대, 시계열, 네트워크 그래프 지원
- 호환 가능한 차트와 실제 필드만 선택할 수 있는 별도 LLM 시각화 설계기
- 각 데이터 포인트에 NCT ID, 원본 필드 경로, 값, 제목, URL 연결
- 필요할 때만 수행하는 연구 상세 조회
- 툴팁, 강조, 확대, 네트워크 상호작용을 지원하는 ECharts 프론트엔드
- JSONL 감사 로그 및 과거 결과 재생이 가능한 모니터링 UI
- OpenAI API 키가 없거나 시각화 설계가 실패할 때 규칙 기반 폴백

## 아키텍처

```text
사용자 질문 + 선택적 구조화 필드
                  │
                  ▼
          LLM Planner (툴콜링)
                  │
          검증된 AnalysisPlan
                  │
                  ▼
            API 요청 컴파일러
                  │
                  ▼
 ClinicalTrials.gov GET /studies
       페이지네이션 + 재시도 + 중복 제거
                  │
                  ▼
         정규화기 + 정확 필터
                  │
                  ▼
       고유 NCT 기반 결정론적 집계기
                  │
            검증된 집계 데이터
                  │
                  ▼
 LLM 시각화 설계기 ── 실패 ──► 결정형 차트 빌더
                  │
                  ▼
      프론트엔드 독립적인 시각화 JSON
                  │
                  ▼
          ECharts 프론트 어댑터
```

### 구성 요소

| 파일 | 역할 |
|---|---|
| `app/planner.py` | 자연어 → 제한된 `AnalysisPlan` |
| `app/clinicaltrials.py` | API 파라미터 컴파일, 재시도, 페이지 수집, 상세 조회 |
| `app/normalizer.py` | 중첩 연구 JSON → 일관된 내부 연구 모델 |
| `app/analysis.py` | 고유 NCT 집계, 네트워크, 출처 연결 |
| `app/visualization.py` | LLM 차트 선택, 스키마 검증, 결정형 폴백 |
| `app/service.py` | 전체 에이전트 워크플로 오케스트레이션 |
| `app/audit.py` | 실행별 JSONL 감사 로그 |
| `app/monitoring.py` | 모니터링 요약과 실행 조회 |
| `app/main.py` | FastAPI 라우트 및 정적 프론트엔드 |
| `app/static/` | User App, Monitoring UI, ECharts 어댑터 |

## 빠른 실행

Python 3.8 이상이 필요합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env`에 OpenAI API 키를 입력합니다.

```dotenv
OPENAI_API_KEY=your-key
OPENAI_MODEL=gpt-5-mini
OPENAI_VISUALIZATION_MODEL=gpt-5-mini
```

애플리케이션을 실행합니다.

```bash
uvicorn app.main:app --reload --port 8000
```

접속 주소:

- User App 및 Monitoring: <http://127.0.0.1:8000/dashboard>
- OpenAPI 문서: <http://127.0.0.1:8000/docs>
- 상태 확인: <http://127.0.0.1:8000/health>

8000 포트를 다른 프로그램이 사용 중이면 `--port 8001`처럼 다른 포트를 지정합니다.

## 환경 설정

| 환경변수 | 기본값 | 설명 |
|---|---:|---|
| `OPENAI_API_KEY` | 빈 값 | LLM 플래너 및 시각화 설계기 활성화 |
| `OPENAI_MODEL` | `gpt-5-mini` | 플래너 모델 |
| `OPENAI_VISUALIZATION_MODEL` | 플래너 모델 | 시각화 설계 모델 |
| `CLINICAL_TRIALS_BASE_URL` | `https://clinicaltrials.gov/api/v2` | ClinicalTrials.gov API 기본 URL |
| `REQUEST_TIMEOUT_SECONDS` | `30` | 외부 API 호출별 timeout |
| `PAGE_SIZE` | `1000` | 페이지당 연구 수, 최대 1000 |
| `MAX_PAGES` | `20` | 컴파일된 검색 하나당 최대 페이지 수 |
| `CITATION_LIMIT` | `20` | 데이터 포인트당 최대 원본 연구 수 |
| `DETAIL_FETCH_LIMIT` | `50` | 다건 상세 조회 헬퍼의 최대 조회 수 |
| `DETAIL_FETCH_CONCURRENCY` | `5` | 다건 상세 조회 헬퍼의 동시 실행 수 |
| `AUDIT_LOG_DIR` | `logs/agent_runs` | JSONL 감사 로그 위치 |

`OPENAI_API_KEY`가 없으면 로컬 개발과 테스트를 위한 제한적인 규칙 기반 플래너 및 결정형 시각화 빌더가 동작합니다.

## API

### `POST /v1/query`

자연어 질문을 하나 이상의 시각화 명세로 변환합니다.

#### 요청 스키마

`query`만 필수입니다. 선택적 구조화 필드는 의도적으로 `query`와 같은 깊이에 배치하며 `filters` 래퍼를 사용하지 않습니다. 사용자가 명시한 구조화 필드는 자연어에서 추출한 값보다 우선합니다.

| 필드 | 타입 | 필수 | 검증 및 의미 |
|---|---|---:|---|
| `query` | string | 예 | 3–2000자 |
| `condition` | string 또는 null | 아니요 | 질환 또는 의학적 상태 |
| `interventions` | string[] | 아니요 | 약물, 생물학적 제제, 기기, 시술 또는 치료 |
| `sponsor` | string 또는 null | 아니요 | 대표 스폰서 또는 기관 |
| `country` | string 또는 null | 아니요 | 임상시험 수행 국가 |
| `overall_statuses` | string[] | 아니요 | ClinicalTrials.gov 전체 상태 값 |
| `phases` | string[] | 아니요 | `PHASE1`, `PHASE2` 등의 정규화된 단계 |
| `study_types` | string[] | 아니요 | `INTERVENTIONAL`, `OBSERVATIONAL` 등 |
| `start_year` | integer 또는 null | 아니요 | 1900–2200 |
| `end_year` | integer 또는 null | 아니요 | 1900–2200, `start_year` 이상 |
| `include_citations` | boolean | 아니요 | 기본값 `true`, 각 datum에 출처 연결 |

자연어만 보내는 요청:

```json
{
  "query": "2018년 이후 미국에서 모집 중인 폐암 임상시험의 연도별 추세를 보여줘."
}
```

구조화 필드를 함께 보내는 요청:

```json
{
  "query": "두 약물의 임상시험 단계를 비교해줘.",
  "condition": "lung cancer",
  "interventions": ["Pembrolizumab", "Nivolumab"],
  "country": "United States",
  "overall_statuses": ["RECRUITING"],
  "start_year": 2018,
  "include_citations": true
}
```

cURL 예시:

```bash
curl -X POST http://127.0.0.1:8000/v1/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"Pembrolizumab과 Nivolumab 임상시험 단계를 비교해줘."}'
```

#### 응답 계약

```json
{
  "query": "Pembrolizumab과 Nivolumab 임상시험 단계를 비교해줘.",
  "plan": {
    "filters": {
      "condition": null,
      "interventions": ["Pembrolizumab", "Nivolumab"],
      "sponsor": null,
      "country": null,
      "overall_statuses": [],
      "phases": [],
      "study_types": [],
      "start_year": null,
      "end_year": null
    },
    "analyses": [
      {
        "id": "compare_phases",
        "type": "comparison",
        "group_by": ["intervention", "phase"],
        "limit": null,
        "minimum_weight": 1
      }
    ],
    "assumptions": []
  },
  "visualizations": [
    {
      "id": "compare_phases",
      "type": "grouped_bar_chart",
      "title": "약물별 임상시험 단계 비교",
      "encoding": {
        "x": {"field": "phase", "type": "nominal"},
        "y": {"field": "trial_count", "type": "quantitative"},
        "series": {"field": "intervention", "type": "nominal"}
      },
      "data": [
        {
          "intervention": "Pembrolizumab",
          "phase": "PHASE2",
          "trial_count": 120,
          "citations": [
            {
              "nct_id": "NCT01234567",
              "field_path": "protocolSection.designModule.phases",
              "value": "PHASE2",
              "source_url": "https://clinicaltrials.gov/study/NCT01234567",
              "title": "예시 연구"
            }
          ]
        }
      ],
      "metadata": {
        "metric": "distinct_nct_id_count",
        "design_source": "llm",
        "candidate_chart_types": ["grouped_bar_chart", "bar_chart"]
      }
    }
  ],
  "meta": {
    "request_id": "uuid",
    "source": "ClinicalTrials.gov",
    "api_version": "2.x",
    "data_timestamp": "ISO-8601 timestamp",
    "records_retrieved": 4938,
    "records_used": 4648,
    "retrieval": {"requests": []},
    "detail_retrieval": {"strategy": "on_demand"},
    "agent_trace": []
  }
}
```

위 숫자는 스키마 설명용 예시이며 실제 집계값은 항상 실시간 API 응답에서 계산합니다.

### `GET /v1/studies/{nct_id}`

특정 연구의 ClinicalTrials.gov 전체 레코드를 반환합니다.

```http
GET /v1/studies/NCT01234567
```

NCT ID는 `NCT` 다음에 숫자 8개가 오는 형식이어야 합니다. User App에서 사용자가 NCT 인용을 선택할 때만 호출합니다. 차트 질의가 연구별 상세 API를 자동으로 대량 호출하지 않습니다.

### 모니터링 엔드포인트

```http
GET /v1/monitoring/runs?limit=50&status=success
GET /v1/monitoring/runs/{request_id}
```

첫 번째 엔드포인트는 대시보드 요약과 집계 지표를 반환합니다. 두 번째는 검증된 계획, 외부 API 호출, 파이프라인 이벤트, 오류, 결과 요약, 다시 렌더링 가능한 `response_output`을 포함한 전체 실행 기록을 반환합니다.

## ClinicalTrials.gov 조회 전략

### 검색 엔드포인트

모든 차트 데이터는 다음 API를 통해 가져옵니다.

```http
GET https://clinicaltrials.gov/api/v2/studies
```

컴파일러는 내부 필드를 전용 검색 파라미터로 변환합니다.

| 내부 필터 | ClinicalTrials.gov 파라미터 |
|---|---|
| `condition` | `query.cond` |
| 각 intervention | `query.intr` |
| `sponsor` | `query.spons` |
| `country` | `query.locn` |

현재 지원하는 집계에 필요한 필드만 요청합니다.

```text
NCTId, BriefTitle, OverallStatus, StartDate, Phase, StudyType,
EnrollmentCount, Condition, InterventionName, InterventionType,
LeadSponsorName, LeadSponsorClass, LocationCountry
```

상태, 단계, 연구 유형, 연도 범위는 정규화 후 코드에서 정확 필터로 적용합니다.

### `/studies`를 여러 번 호출하는 이유

1. **페이지네이션:** API는 한 번에 최대 `PAGE_SIZE`개의 연구를 반환합니다. 모든 결과를 수집할 때까지 `nextPageToken`을 따라갑니다.
2. **약물 비교:** 요청한 약물을 각각 검색합니다. 예를 들어 `query.intr=Pembrolizumab`, `query.intr=Nivolumab`을 별도로 호출한 뒤 NCT ID로 합치고 중복을 제거합니다.
3. **재시도:** timeout, 네트워크 오류, HTTP 429 및 일부 5xx 응답은 제한된 지수 백오프로 재시도합니다.

`MAX_PAGES` 이후에도 다음 페이지가 남아 있으면 부분 통계를 반환하지 않고 오류로 처리합니다.

### 상세 조회 정책

목록 API는 현재 지원하는 차트에 필요한 필드를 모두 제공합니다. 따라서 차트 생성과 인용을 위해 각 연구의 상세 API를 호출할 필요가 없습니다.

```text
차트 요청   → GET /studies 여러 페이지 → 집계 → 시각화
NCT 클릭    → GET /studies/{nctId}      → 상세 패널
```

이 on-demand 정책은 수십 개의 상세 호출로 인한 지연을 방지하고, 개별 상세 요청 오류가 이미 완료된 차트 집계를 실패시키지 않도록 합니다.

## 에이전트 설계

### 1. LLM Planner

Planner에는 다음 정보가 전달됩니다.

- 원래 사용자 질문
- 사용자가 명시한 구조화 필드
- 허용된 필터, 분석 유형, 그룹 차원을 정의한 JSON Schema
- 각 내부 변수의 의미와 정규화 규칙

LLM은 `submit_analysis_plan`을 호출해야 합니다. 이후 Pydantic이 알 수 없는 필드와 잘못된 조합을 거부합니다.

지원 분석 유형:

- `time_trend`
- `distribution`
- `comparison`
- `ranking`
- `network`

지원 차원:

- `year`
- `phase`
- `status`
- `intervention`
- `intervention_type`
- `sponsor`
- `sponsor_class`
- `country`

주요 의미 검증 규칙:

- 시계열은 반드시 `year`로 그룹화
- 비교는 두 개 이상의 차원 필요
- 네트워크는 정확히 두 개의 차원 필요
- 질문에 직접 등장하지 않은 연도 제거
- 한국어 의학 용어를 ClinicalTrials.gov 검색용 영어로 정규화
- 명시적 구조화 필드가 LLM 추출값보다 우선

### 2. 결정론적 데이터 파이프라인

LLM은 API URL을 작성하거나 숫자를 계산하지 않습니다. 코드는 다음을 수행합니다.

- 내부 계획을 API 파라미터로 매핑
- 모든 페이지 조회
- 중첩 JSON 정규화
- 정확 후처리 필터
- 약물명 대소문자를 요청한 표준 이름으로 통합
- 고유 NCT ID 기준 계산
- 그룹화, 정렬, 순위 및 네트워크 엣지 계산
- 각 결과에 원본 연구 연결

집계는 NCT ID 집합을 사용하므로 중복 레코드나 다중값 필드가 동일 버킷의 연구 수를 부풀리지 않습니다.

### 3. LLM 시각화 설계기

집계 이후 별도의 LLM 단계에는 다음만 전달합니다.

- 원래 질문
- 검증된 분석 작업
- 검증된 집계 데이터
- 실제 데이터 필드 목록
- 호환 가능한 차트 후보

LLM은 `submit_visualization_design`을 통해 `type`, `title`, `encoding`, 표시용 metadata만 반환합니다. `data` 배열은 교체할 수 없습니다. 서비스가 선택된 차트와 참조 필드를 검증한 뒤 결정론적 집계 데이터를 결합합니다.

결과 형태별 차트 후보:

| 결과 형태 | 후보 |
|---|---|
| 시계열 | `time_series`, `bar_chart` |
| 순위 | `horizontal_bar_chart`, `bar_chart` |
| 다차원 비교 | `grouped_bar_chart`, `bar_chart` |
| 단일 차원 분포 | `bar_chart`, `horizontal_bar_chart` |
| 네트워크 | `network_graph` |

모델이 실패하거나 호환되지 않는 차트를 선택하거나 존재하지 않는 필드를 참조하면 결정형 빌더가 대신 시각화를 만듭니다. `metadata.design_source`에서 `llm` 또는 `deterministic_fallback`을 확인할 수 있습니다.

## 프론트엔드

첫 화면은 **User App** 탭입니다. 자연어 질문을 `/v1/query`에 보내고 라이브러리 독립적인 응답 JSON을 ECharts 옵션으로 변환해 반환된 모든 시각화를 렌더링합니다.

지원 상호작용:

- 호버 툴팁
- 축 및 시리즈 강조
- 시계열 확대 및 스크롤
- 네트워크 확대, 이동, 인접 관계 강조, 노드 드래그
- 원본 연구 목록 펼치기
- NCT 선택 후 필요할 때 상세 조회
- 전체 응답 JSON 확인

**Monitoring** 탭에서는 최근 실행, 요청 파라미터, 상태, 시간, 레코드 수, API 호출, 응답 요약 및 파이프라인 이벤트를 확인합니다. `View result` 버튼은 User App으로 이동하여 저장된 `response_output`을 다시 렌더링합니다. 결과 재생 기능 추가 전에 생성된 로그에는 해당 필드가 없습니다.

ECharts는 `app/static/index.html`에 고정된 CDN 버전으로 로드합니다. 백엔드 응답은 특정 렌더러에 종속되지 않으며 `app/static/app.js`가 Cheiron 시각화 계약을 ECharts 옵션으로 변환합니다.

## 출처와 인용

각 표 형식 datum 또는 네트워크 edge는 다음과 같은 원본 참조를 포함할 수 있습니다.

```json
{
  "nct_id": "NCT01234567",
  "field_path": "protocolSection.designModule.phases",
  "value": "PHASE2",
  "source_url": "https://clinicaltrials.gov/study/NCT01234567",
  "title": "연구 제목"
}
```

`CITATION_LIMIT`는 데이터 포인트당 첨부하는 참조 수를 제한하며 집계에 포함되는 연구 수를 제한하지 않습니다. 화면의 “원본 연구 188개”는 시각화 전체에 연결된 고유 NCT 참조가 188개라는 의미이며 상세 API를 188번 호출했다는 의미가 아닙니다.

## 감사 로그와 모니터링

각 `/v1/query` 실행은 다음 파일에 한 줄씩 추가됩니다.

```text
logs/agent_runs/YYYY-MM-DD.jsonl
```

각 레코드에는 다음이 포함됩니다.

- 요청 ID, 시작·완료 시각, 상태
- 원래 사용자 요청
- 검증된 분석 계획
- 순서가 기록된 ClinicalTrials.gov API 호출
- 최종 URL, 인코딩된 query string, 파라미터, 안전한 헤더, 시도 횟수, 상태, 소요 시간
- 재현 가능한 cURL 명령
- 페이지별 NCT ID와 제목 응답 요약
- 파이프라인 이벤트
- 결과 요약 또는 구조화된 오류
- Monitoring에서 User App으로 재생하기 위한 전체 `response_output`

비밀키와 인증 헤더는 기록하지 않습니다. `Accept`, `Content-Type`, `User-Agent`처럼 허용된 헤더만 보관합니다.

## 예상 질문

```text
폐암 임상시험을 단계별로 보여줘.
2018년 이후 폐암 임상시험 수의 연도별 추세를 보여줘.
Pembrolizumab과 Nivolumab 임상시험 단계를 비교해줘.
모집 중인 유방암 임상시험이 가장 많은 국가를 보여줘.
폐암 임상시험 스폰서 상위 10개를 보여줘.
폐암 연구의 스폰서와 약물 관계를 네트워크로 보여줘.
폐암 병용요법에서 함께 사용되는 약물 네트워크를 보여줘.
당뇨병 임상시험의 중재 유형 분포를 보여줘.
관찰연구와 중재연구의 연도별 건수를 비교해줘.
NCT01234567 연구의 상세 정보를 보여줘.
```

## 테스트

외부 네트워크를 사용하지 않는 단위 테스트:

```bash
pytest -q
```

테스트는 mock HTTP 및 LLM 클라이언트를 사용하며 다음을 검증합니다.

- 정규화 및 정확 필터
- 고유 NCT 집계
- 약물명 대소문자 통합
- 네트워크 엣지 가중치
- 엄격한 계획 검증
- 최상위 요청 필드
- 목록·상세 API 감사 로그
- 제한된 다건 상세 조회 헬퍼
- 모니터링 JSONL 조회
- 데이터 변경 없는 LLM 시각화 선택
- 전체 서비스 응답 및 재생 가능한 감사 출력

실제 ClinicalTrials.gov를 이용한 선택적 smoke test:

```bash
python3 scripts/smoke_test.py
```

## 주요 설계 결정과 트레이드오프

- **LLM은 의도를, 코드는 사실을 담당:** 환각 위험을 낮추고 계산을 재현할 수 있습니다.
- **라이브러리 독립적인 백엔드 계약:** ECharts, Vega-Lite 또는 다른 렌더러에서도 API를 사용할 수 있습니다.
- **넓은 검색 후 정확 필터:** API 컴파일은 단순하지만 고급 검색식을 모두 컴파일하는 방식보다 많은 레코드를 가져올 수 있습니다.
- **약물별 독립 검색:** 비교 요청을 이해하고 감사하기 쉽지만 페이지 호출 수가 증가합니다.
- **메모리 내 집계:** 과제 시간 범위에는 적절하지만 매우 넓은 질의는 메모리와 시간이 더 필요합니다.
- **필요할 때만 상세 조회:** 차트 가용성과 응답 시간을 보호하지만 최초 응답에는 모든 중첩 상세 필드가 들어가지 않습니다.
- **JSONL 감사 저장:** 투명하고 확인하기 쉽지만 운영 환경에서는 구조화 저장소와 보존 정책이 필요합니다.

## 현재 제한과 개선 방향

- 대표 자연어 질문 평가 세트를 추가하여 플래너 정확도 측정
- 더 많은 정확 필터를 ClinicalTrials.gov `query.term` / `AREA[...]` 검색식으로 컴파일하여 조회량 감소
- 직접적인 영어 정규화를 넘어 의학 용어 및 약물 동의어 처리 강화
- 캐시, 동일 요청 병합, 백그라운드 작업, 요청별 비용·시간 제한 추가
- 감사 로그를 검색 가능한 데이터베이스로 이동하고 보존·마스킹 정책 적용
- 오프라인 배포를 위해 CDN 대신 ECharts 번들링
- 지도, 산점도, 히스토그램, 결과 통계, 연령, 성별, 선정 기준 차원 추가
- 운영용 인증, rate limiting 및 배포 설정 추가

## AI 도구 사용 및 무결성 설명

OpenAI 모델은 제한된 계획 생성과 시각화 설계에 사용합니다. 애플리케이션 코드는 검증, API 요청 구성, 페이지네이션, 데이터 정규화, NCT 중복 제거, 집계, 인용 및 오류 처리를 직접 담당합니다. 정확성은 엄격한 Pydantic 스키마, 의미 검증기, mock 기반 테스트, 실제 API smoke test, 모니터링 trace, 결정형 폴백으로 확인합니다.

구현은 AI의 도움을 받아 반복적으로 설계, 생성, 검토, 테스트 및 수정했습니다. 계획과 계산의 분리, 렌더러 독립 출력, 제한된 조회, on-demand 상세 정책, 감사 trace 설계는 검증되지 않은 모델 출력이 아니라 명시적인 애플리케이션 수준의 설계 결정입니다.

## 라이선스

현재 프로젝트 라이선스는 별도로 지정하지 않았습니다. ClinicalTrials.gov 데이터는 공개 API에서 조회하며 원본 제공처의 약관과 정책을 따릅니다.
