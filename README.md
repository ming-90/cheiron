# Cheiron — ClinicalTrials.gov Query-to-Visualization Agent

Cheiron is an AI-enabled service that turns natural-language clinical-trial questions into frontend-renderable visualization JSON backed by live [ClinicalTrials.gov Data API](https://clinicaltrials.gov/data-api/api) records.

The system uses an LLM for constrained planning and visualization design. It does **not** ask the LLM to search records, calculate statistics, or invent chart data. API compilation, pagination, normalization, filtering, distinct-NCT aggregation, citations, and output validation are implemented in deterministic Python code.

A built-in web application renders the returned JSON with ECharts and provides an audit dashboard for inspecting every agent run and ClinicalTrials.gov request.

## Features

- Natural-language questions in Korean or English
- OpenAI tool calling with a strict, predefined `AnalysisPlan`
- Optional structured filters at the same depth as `query`
- ClinicalTrials.gov `/studies` pagination, retry, and NCT-ID deduplication
- Deterministic time-trend, distribution, comparison, ranking, and network aggregation
- Multiple chart types: bar, horizontal bar, grouped bar, time series, and network graph
- Separate LLM visualization designer constrained to compatible chart types and existing fields
- Datum-level provenance with NCT ID, source field path, value, title, and source URL
- On-demand study detail retrieval
- ECharts rendering with tooltips, highlighting, zooming, and graph interaction
- JSONL audit logs and a monitoring UI with replayable results
- Rule-based fallbacks when no OpenAI API key is configured or visualization design fails

## Architecture

```text
User question + optional structured fields
                  │
                  ▼
        LLM Planner (tool calling)
                  │
          validated AnalysisPlan
                  │
                  ▼
        API request compiler
                  │
                  ▼
 ClinicalTrials.gov GET /studies
     pagination + retry + deduplication
                  │
                  ▼
       Normalizer + exact filters
                  │
                  ▼
  Deterministic distinct-NCT aggregator
                  │
           verified aggregate data
                  │
                  ▼
 LLM visualization designer ── failure ──► deterministic chart builder
                  │
                  ▼
       frontend-independent JSON
                  │
                  ▼
        ECharts frontend adapter
```

### Component map

| File | Responsibility |
|---|---|
| `app/planner.py` | Natural language → constrained `AnalysisPlan` |
| `app/clinicaltrials.py` | API parameter compilation, retry, pagination, detail lookup |
| `app/normalizer.py` | Nested study JSON → consistent internal study model |
| `app/analysis.py` | Distinct-NCT aggregation, networks, provenance |
| `app/visualization.py` | LLM chart selection, schema checks, deterministic fallback |
| `app/service.py` | End-to-end agent orchestration |
| `app/audit.py` | Per-run JSONL audit records |
| `app/monitoring.py` | Monitoring summaries and run lookup |
| `app/main.py` | FastAPI routes and static frontend |
| `app/static/` | User App, Monitoring UI, ECharts adapter |

## Quick start

Python 3.8 or later is required.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Add an OpenAI API key to `.env`:

```dotenv
OPENAI_API_KEY=your-key
OPENAI_MODEL=gpt-5-mini
OPENAI_VISUALIZATION_MODEL=gpt-5-mini
```

Start the application:

```bash
uvicorn app.main:app --reload --port 8000
```

Open:

- User App and Monitoring: <http://127.0.0.1:8000/dashboard>
- OpenAPI documentation: <http://127.0.0.1:8000/docs>
- Health check: <http://127.0.0.1:8000/health>

If port 8000 is already in use, choose another port such as `--port 8001`.

## Configuration

| Environment variable | Default | Purpose |
|---|---:|---|
| `OPENAI_API_KEY` | empty | Enables the LLM planner and visualization designer |
| `OPENAI_MODEL` | `gpt-5-mini` | Planner model |
| `OPENAI_VISUALIZATION_MODEL` | planner model | Visualization-design model |
| `CLINICAL_TRIALS_BASE_URL` | `https://clinicaltrials.gov/api/v2` | ClinicalTrials.gov API base URL |
| `REQUEST_TIMEOUT_SECONDS` | `30` | Timeout for each external API request |
| `PAGE_SIZE` | `1000` | Studies per page, capped at 1000 |
| `MAX_PAGES` | `20` | Maximum pages per compiled search |
| `CITATION_LIMIT` | `20` | Maximum source records attached to each datum |
| `DETAIL_FETCH_LIMIT` | `50` | Limit for the reusable bulk-detail helper |
| `DETAIL_FETCH_CONCURRENCY` | `5` | Concurrency for the reusable bulk-detail helper |
| `AUDIT_LOG_DIR` | `logs/agent_runs` | JSONL audit-log directory |

Without `OPENAI_API_KEY`, a limited rule-based planner and deterministic visualization builder are used for local development and tests.

## API

### `POST /v1/query`

Converts a natural-language question into one or more visualization specifications.

#### Request schema

Only `query` is required. Optional structured fields are intentionally placed at the same depth as `query`; there is no `filters` wrapper. Explicit fields override values extracted from natural language.

| Field | Type | Required | Validation / meaning |
|---|---|---:|---|
| `query` | string | yes | 3–2000 characters |
| `condition` | string or null | no | Disease or medical condition |
| `interventions` | string[] | no | Drugs, biologics, devices, procedures, or treatments |
| `sponsor` | string or null | no | Lead sponsor or organization |
| `country` | string or null | no | Trial-location country |
| `overall_statuses` | string[] | no | ClinicalTrials.gov overall-status values |
| `phases` | string[] | no | Normalized phase values such as `PHASE1`, `PHASE2` |
| `study_types` | string[] | no | Values such as `INTERVENTIONAL`, `OBSERVATIONAL` |
| `start_year` | integer or null | no | 1900–2200 |
| `end_year` | integer or null | no | 1900–2200 and not earlier than `start_year` |
| `include_citations` | boolean | no | Defaults to `true`; attaches provenance to each datum |

Natural-language-only request:

```json
{
  "query": "Show the annual trend of recruiting lung-cancer trials in the United States since 2018."
}
```

Request with explicit fields:

```json
{
  "query": "Compare the clinical-trial phases for these two drugs.",
  "condition": "lung cancer",
  "interventions": ["Pembrolizumab", "Nivolumab"],
  "country": "United States",
  "overall_statuses": ["RECRUITING"],
  "start_year": 2018,
  "include_citations": true
}
```

Example cURL:

```bash
curl -X POST http://127.0.0.1:8000/v1/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"Compare the trial phases of Pembrolizumab and Nivolumab."}'
```

#### Response contract

| Field | Type | Contract |
|---|---|---|
| `query` | string | Original natural-language question |
| `plan` | object | Validated filters, 1–5 analysis tasks, and explicit assumptions |
| `visualizations` | array | One renderable specification per analysis task |
| `visualizations[].id` | string | Stable analysis/visualization identifier |
| `visualizations[].type` | string | One of the supported chart types documented below |
| `visualizations[].title` | string | Human-readable chart title |
| `visualizations[].encoding` | object | Field-to-channel mapping using `x`, `y`, optional `series`, or network `nodes`/`edges` |
| `visualizations[].data` | array | Verified rows, or node/edge objects for a network |
| `visualizations[].metadata` | object | Metric, display hints, chart candidates, and design source |
| `meta` | object | Request ID, source/version timestamps, counts, retrieval details, detail policy, and agent trace |

Counts use `distinct_nct_id_count`. Every encoding field must exist in `data`; the backend validates this before returning the response.

```json
{
  "query": "Compare the trial phases of Pembrolizumab and Nivolumab.",
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
      "title": "Trial count by drug and phase",
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
              "title": "Example study"
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

The example values above illustrate the schema; actual counts always come from the live API response.

### `GET /v1/studies/{nct_id}`

Returns the complete ClinicalTrials.gov record for one study.

```http
GET /v1/studies/NCT01234567
```

The NCT ID must match `NCT` followed by eight digits. The User App calls this endpoint only when a user selects an NCT citation. Chart queries do not automatically fan out to detail endpoints.

### Monitoring endpoints

```http
GET /v1/monitoring/runs?limit=50&status=success
GET /v1/monitoring/runs/{request_id}
```

The first endpoint returns dashboard summaries and aggregate metrics. The second returns a complete audit record, including the validated plan, external API calls, pipeline events, errors, result summary, and replayable `response_output`.

## ClinicalTrials.gov retrieval strategy

### Search endpoint

All chart data is retrieved through:

```http
GET https://clinicaltrials.gov/api/v2/studies
```

The compiler maps internal fields to dedicated query parameters:

| Internal filter | ClinicalTrials.gov parameter |
|---|---|
| `condition` | `query.cond` |
| each intervention | `query.intr` |
| `sponsor` | `query.spons` |
| `country` | `query.locn` |

The client requests only the fields currently required for supported aggregations:

```text
NCTId, BriefTitle, OverallStatus, StartDate, Phase, StudyType,
EnrollmentCount, Condition, InterventionName, InterventionType,
LeadSponsorName, LeadSponsorClass, LocationCountry
```

Status, phase, study type, and year ranges are applied as exact deterministic filters after normalization.

### Why `/studies` may be called multiple times

1. **Pagination:** the API returns at most `PAGE_SIZE` studies per request. The client follows `nextPageToken` until all pages are collected or `MAX_PAGES` is reached.
2. **Intervention comparison:** each requested intervention is searched independently, for example `query.intr=Pembrolizumab` and `query.intr=Nivolumab`. Results are merged and deduplicated by NCT ID.
3. **Retry:** timeouts, network errors, HTTP 429, and selected 5xx responses are retried with bounded exponential backoff.

If a next-page token remains after `MAX_PAGES`, the service refuses to return partial statistics.

### Detail endpoint policy

The list endpoint already supplies every field needed for the currently supported charts. Therefore chart generation and citations do not require one detail request per study.

```text
chart request → GET /studies pages → aggregate → visualization
NCT click     → GET /studies/{nctId} → detail drawer
```

This on-demand policy prevents dozens of detail calls from increasing latency or causing a completed aggregation to fail because an individual detail request timed out.

## Agent design

### 1. LLM planner

The planner receives:

- the original question;
- any explicit structured fields;
- a JSON Schema defining every allowed filter, analysis type, and group-by dimension;
- semantic descriptions and normalization rules.

The LLM must call `submit_analysis_plan`. Pydantic then rejects unknown fields and invalid combinations.

Supported analysis types:

- `time_trend`
- `distribution`
- `comparison`
- `ranking`
- `network`

Supported dimensions:

- `year`
- `phase`
- `status`
- `intervention`
- `intervention_type`
- `sponsor`
- `sponsor_class`
- `country`

Semantic constraints include:

- a time trend must group by `year`;
- a comparison requires at least two dimensions;
- a network requires exactly two dimensions;
- years not explicitly present in the question are removed;
- Korean medical terms are normalized to English ClinicalTrials.gov search terms;
- explicit structured fields override extracted values.

### 2. Deterministic data pipeline

The LLM does not write API URLs or perform calculations. Code performs:

- internal-plan-to-API parameter mapping;
- all-page retrieval;
- nested JSON normalization;
- exact post-filtering;
- intervention-name case normalization;
- distinct NCT-ID counting;
- grouping, sorting, ranking, and network edge calculation;
- provenance attachment.

Counting sets are keyed by NCT ID, so duplicate records and multi-valued fields do not inflate a bucket's trial count.

### 3. LLM visualization designer

After aggregation, a separate LLM step receives:

- the original question;
- the validated analysis task;
- verified aggregate data;
- available data fields;
- compatible chart candidates.

It returns only `type`, `title`, `encoding`, and display metadata through `submit_visualization_design`. It cannot replace the `data` array. The service attaches the deterministic aggregate data after validating the selected chart and all referenced fields.

Candidate chart types are constrained by result shape:

| Result shape | Candidates |
|---|---|
| Time trend | `time_series`, `bar_chart` |
| Ranking | `horizontal_bar_chart`, `bar_chart` |
| Multi-dimension comparison | `grouped_bar_chart`, `bar_chart` |
| Single-dimension distribution | `bar_chart`, `horizontal_bar_chart` |
| Network | `network_graph` |

If the model fails, selects an incompatible chart, or references an unknown field, a deterministic builder produces the visualization instead. `metadata.design_source` reports `llm` or `deterministic_fallback`.

## Frontend

The root page opens on the **User App** tab. It sends natural-language questions to `/v1/query`, converts the library-independent response into ECharts options, and renders every returned visualization.

Supported interactions include:

- hover tooltips;
- axis and series highlighting;
- time-series zoom and scrolling;
- network zoom, pan, adjacency focus, and node dragging;
- citation expansion;
- NCT click-through to on-demand study details;
- raw response JSON inspection.

The **Monitoring** tab shows recent runs, request parameters, status, timing, record counts, API calls, response summaries, and pipeline events. `View result` switches to User App and re-renders the saved `response_output`. Runs created before result replay was introduced do not contain that field.

ECharts is loaded from a pinned CDN version in `app/static/index.html`. The backend response remains renderer-independent; `app/static/app.js` is the adapter from Cheiron's visualization contract to ECharts options.

## Provenance and citations

Each tabular datum or network edge can include source references:

```json
{
  "nct_id": "NCT01234567",
  "field_path": "protocolSection.designModule.phases",
  "value": "PHASE2",
  "source_url": "https://clinicaltrials.gov/study/NCT01234567",
  "title": "Study title"
}
```

`CITATION_LIMIT` limits references per datum, not the number of studies counted. A UI label such as “188 source studies” means 188 unique NCT references are attached across the visualization; it does not mean 188 detail API calls were made.

## Audit logging and monitoring

Every `/v1/query` run is appended to:

```text
logs/agent_runs/YYYY-MM-DD.jsonl
```

Each record contains:

- request ID, timestamps, and status;
- original user request;
- validated analysis plan;
- ordered ClinicalTrials.gov API calls;
- final URL, encoded query string, parameters, safe headers, attempt number, status, and duration;
- replayable cURL command;
- page-level response summary with NCT IDs and titles;
- pipeline events;
- result summary or structured error;
- complete `response_output` for Monitoring → User App replay.

Secrets and authorization headers are never logged. Only allow-listed headers such as `Accept`, `Content-Type`, and `User-Agent` are retained.

## Example questions

```text
Show lung-cancer trials by phase.
How has the number of lung-cancer trials changed each year since 2018?
Compare the clinical-trial phases of Pembrolizumab and Nivolumab.
Which countries have the most recruiting breast-cancer trials?
Show the top 10 sponsors of lung-cancer trials.
Show a sponsor-to-drug network for lung-cancer trials.
Show a drug co-occurrence network for lung-cancer combination studies.
Show intervention-type distribution for diabetes trials.
Compare annual observational and interventional study counts.
Show the full details for NCT01234567.
```

## Actual example runs

The repository includes three complete, unedited `response_output` objects captured from successful live runs on August 9, 2026. They satisfy the assignment requirement for 3–5 example queries with the actual JSON produced by the system. Because ClinicalTrials.gov is a live source, later runs may produce different counts.

| Query | Actual output |
|---|---|
| Compare the clinical-trial phases of Pembrolizumab and Nivolumab. | [`examples/01-drug-phase-comparison.json`](examples/01-drug-phase-comparison.json) |
| Show the top 10 countries with the most breast-cancer clinical trials. | [`examples/02-country-ranking.json`](examples/02-country-ranking.json) |
| Show the top 10 sponsors of lung-cancer clinical trials. | [`examples/03-sponsor-ranking.json`](examples/03-sponsor-ranking.json) |

Each file contains the complete returned plan, visualization specification, data, provenance citations, and retrieval metadata. Per-attempt operational logs remain local under `logs/`.

## Testing

Run the offline unit suite:

```bash
pytest -q
```

The tests use mock HTTP and LLM clients. They cover:

- normalization and exact filtering;
- distinct-NCT aggregation;
- intervention-name case normalization;
- network edge weights;
- strict plan validation;
- flat request fields;
- list and detail API audit logs;
- bounded detail helper behavior;
- monitoring JSONL lookup;
- LLM visualization selection without data mutation;
- complete service response and replayable audit output.

Run an optional live ClinicalTrials.gov smoke test:

```bash
python3 scripts/smoke_test.py
```

## Design decisions and trade-offs

- **LLM for intent, code for facts:** reduces hallucination risk and makes calculations reproducible.
- **Library-independent backend contract:** keeps the API usable by ECharts, Vega-Lite, or another renderer.
- **Broad search plus exact post-filtering:** simplifies parameter compilation, but can retrieve more records than a fully compiled advanced-search expression.
- **Separate intervention searches:** produces understandable, auditable comparison calls, but increases page requests.
- **In-memory aggregation:** appropriate for the take-home time box; very broad queries use more memory and latency.
- **On-demand details:** protects chart availability and latency; the initial response does not include every nested study field.
- **JSONL audit storage:** transparent and easy to inspect, but a production system should use structured storage and retention policies.

## Known limitations and next steps

- Add a representative natural-language evaluation set for planner accuracy.
- Compile more exact filters into ClinicalTrials.gov `query.term` / `AREA[...]` expressions to reduce retrieval volume.
- Add medical terminology and drug-synonym normalization beyond direct English normalization.
- Add caching, request coalescing, background jobs, and per-request cost/time budgets.
- Move audit records to a queryable database and add retention/redaction controls.
- Vendor or bundle ECharts instead of relying on a CDN for offline deployments.
- Add maps, scatter plots, histograms, outcome-result statistics, age, sex, and eligibility dimensions.
- Add authentication, rate limiting, and deployment configuration for production use.

## AI-tool usage and integrity note

OpenAI models are used at runtime for constrained plan generation and visualization design. OpenAI Codex was used as an AI-assisted development tool for implementation, review, documentation, and test iteration. The application code deliberately owns validation, API request construction, pagination, data normalization, NCT deduplication, aggregation, citations, and error handling. Correctness is checked through strict Pydantic schemas, semantic validators, mock-based tests, live API smoke tests, monitoring traces, and deterministic fallbacks.

The implementation was iteratively designed, generated, reviewed, tested, and adapted with AI assistance. Engineering decisions—including the separation of planning from calculation, renderer-independent output, bounded retrieval, on-demand detail policy, and audit trace design—are explicit application-level choices rather than unchecked model output.

## License

No project license has been specified. ClinicalTrials.gov data is retrieved from the public API and remains subject to its source terms and policies.
