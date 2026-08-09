import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from app.audit import AuditRun
from app.clinicaltrials import ClinicalTrialsClient
from app.analysis import aggregate
from app.models import (
    AnalysisPlan, AnalysisTask, AnalysisType, Dimension, Filters, QueryRequest, QueryResponse,
    Visualization,
)
from app.monitoring import dashboard_stats, get_run, list_runs
from app.normalizer import apply_exact_filters, normalize_many
from app.service import QueryService
from app.planner import Planner
from app.visualization import VisualizationBuilder, build_visualization


def raw_study(
    nct_id, year, phase, intervention, sponsor, country="United States",
    status="RECRUITING",
):
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct_id, "briefTitle": f"Study {nct_id}"},
            "statusModule": {
                "overallStatus": status,
                "startDateStruct": {"date": f"{year}-01-01"},
            },
            "conditionsModule": {"conditions": ["Lung Cancer"]},
            "designModule": {
                "studyType": "INTERVENTIONAL", "phases": [phase],
                "enrollmentInfo": {"count": 100},
            },
            "armsInterventionsModule": {
                "interventions": [{"name": intervention, "type": "DRUG"}]
            },
            "sponsorCollaboratorsModule": {
                "leadSponsor": {"name": sponsor, "class": "INDUSTRY"}
            },
            "contactsLocationsModule": {"locations": [{"country": country}]},
        }
    }


RAW = [
    raw_study("NCT00000001", 2020, "PHASE2", "Pembrolizumab", "Sponsor A"),
    raw_study("NCT00000002", 2020, "PHASE3", "Pembrolizumab", "Sponsor A"),
    raw_study("NCT00000003", 2021, "PHASE3", "Nivolumab", "Sponsor B"),
    raw_study("NCT00000004", 2017, "PHASE1", "Pembrolizumab", "Sponsor C"),
]


def test_normalize_filter_and_distinct_aggregation():
    studies = normalize_many(RAW + [RAW[0]])
    filtered = apply_exact_filters(studies, Filters(start_year=2018, country="United States"))
    task = AnalysisTask(
        id="compare", type=AnalysisType.COMPARISON,
        group_by=[Dimension.INTERVENTION, Dimension.PHASE],
    )
    result = aggregate(filtered, task, ["Pembrolizumab", "Nivolumab"])
    counts = {
        (row["intervention"], row["phase"]): row["trial_count"] for row in result["rows"]
    }
    assert counts == {
        ("Pembrolizumab", "PHASE2"): 1,
        ("Pembrolizumab", "PHASE3"): 1,
        ("Nivolumab", "PHASE3"): 1,
    }
    assert result["rows"][0]["citations"][0]["nct_id"].startswith("NCT")
    evidence_paths = {
        item["field_path"] for item in result["rows"][0]["citations"][0]["evidence"]
    }
    assert evidence_paths == {
        "protocolSection.armsInterventionsModule.interventions.name",
        "protocolSection.designModule.phases",
    }
    assert result["rows"][0]["source_count"] == result["rows"][0]["trial_count"]
    assert result["rows"][0]["citations_truncated"] is False


def test_comparison_normalizes_intervention_name_case_to_requested_name():
    studies = normalize_many([
        raw_study("NCT10000001", 2020, "PHASE2", "NIVOLUMAB", "Sponsor A"),
        raw_study("NCT10000002", 2021, "PHASE2", "Nivolumab", "Sponsor B"),
    ])
    task = AnalysisTask(
        id="compare", type=AnalysisType.COMPARISON,
        group_by=[Dimension.INTERVENTION, Dimension.PHASE],
    )
    result = aggregate(studies, task, ["Nivolumab"])
    assert [(row["intervention"], row["trial_count"]) for row in result["rows"]] == [
        ("Nivolumab", 2)
    ]


def test_network_uses_distinct_trials_as_edge_weight():
    studies = normalize_many(RAW)
    task = AnalysisTask(
        id="network", type=AnalysisType.NETWORK,
        group_by=[Dimension.SPONSOR, Dimension.INTERVENTION],
    )
    result = aggregate(studies, task)
    edge = next(item for item in result["edges"] if item["source"] == "Sponsor A")
    assert edge["target"] == "Pembrolizumab"
    assert edge["weight"] == 2
    assert len(edge["citations"][0]["evidence"]) == 2
    sponsor_node = next(
        item for item in result["nodes"]
        if item["group"] == "sponsor" and item["id"] == "Sponsor A"
    )
    assert sponsor_node["trial_count"] == 2
    assert sponsor_node["source_count"] == 2
    assert sponsor_node["citations"][0]["evidence"][0]["value"] == "Sponsor A"


class FakePlanner:
    async def create_plan(self, query, supplied_filters):
        return AnalysisPlan(
            filters=Filters(start_year=2018),
            analyses=[AnalysisTask(
                id="trend", type=AnalysisType.TIME_TREND, group_by=[Dimension.YEAR]
            )],
        )


class FakeClinicalTrials:
    async def search(self, plan, audit=None):
        return RAW, {"requests": [{
            "query_params": {}, "fields": [], "pages": 1,
            "truncated": False, "retrieved_count": len(RAW), "total_count": len(RAW),
        }]}

    async def get_version(self, audit=None):
        return {"apiVersion": "test", "dataTimestamp": "2026-01-01T00:00:00"}

    async def get_studies_detail(self, nct_ids, audit=None):
        raise AssertionError("chart queries must not fan out to detail endpoints")

    async def close(self):
        return None


class FakeVisualizationBuilder:
    async def build(self, query, task, result):
        visualization = build_visualization(task, result)
        visualization.metadata["design_source"] = "test"
        return visualization


def test_service_returns_renderable_json(tmp_path, monkeypatch):
    import app.service as service_module

    monkeypatch.setattr(service_module, "settings", SimpleNamespace(audit_log_dir=str(tmp_path)))
    service = QueryService(
        planner=FakePlanner(), clinical_trials=FakeClinicalTrials(),
        visualization_builder=FakeVisualizationBuilder(),
    )
    result = asyncio.run(service.execute(QueryRequest(query="2018년 이후 연도별 추세")))
    body = result.dict()
    assert body["visualizations"][0]["type"] == "time_series"
    assert body["visualizations"][0]["encoding"]["x"]["field"] == "year"
    assert body["meta"]["records_used"] == 3
    assert body["meta"]["api_version"] == "test"
    assert body["meta"]["request_id"]
    assert body["meta"]["detail_retrieval"]["strategy"] == "on_demand"
    assert body["visualizations"][0]["metadata"]["design_source"] == "test"
    log_files = list(tmp_path.glob("*.jsonl"))
    assert len(log_files) == 1
    audit = json.loads(log_files[0].read_text(encoding="utf-8").strip())
    assert audit["user_request"]["query"] == "2018년 이후 연도별 추세"
    assert audit["status"] == "success"
    assert audit["result_summary"]["records_used"] == 3
    assert audit["response_output"]["query"] == "2018년 이후 연도별 추세"
    assert audit["response_output"]["visualizations"][0]["type"] == "time_series"


def test_service_can_omit_embedded_citations_without_changing_source_count(
    tmp_path, monkeypatch,
):
    import app.service as service_module

    monkeypatch.setattr(service_module, "settings", SimpleNamespace(audit_log_dir=str(tmp_path)))
    service = QueryService(
        planner=FakePlanner(), clinical_trials=FakeClinicalTrials(),
        visualization_builder=FakeVisualizationBuilder(),
    )
    result = asyncio.run(service.execute(QueryRequest(
        query="2018년 이후 연도별 추세", include_citations=False,
    )))
    rows = result.dict(exclude_none=True)["visualizations"][0]["data"]
    assert all(row["citations"] == [] for row in rows)
    assert all(row["source_count"] == row["trial_count"] for row in rows)


def test_planner_removes_unstated_years_and_unsupported_unknown_assumption():
    plan = AnalysisPlan(
        filters=Filters(start_year=2018, end_year=2026),
        analyses=[AnalysisTask(
            id="phase", type=AnalysisType.DISTRIBUTION, group_by=[Dimension.PHASE]
        )],
        assumptions=["Missing phase values are placed in an Unknown bucket"],
    )
    cleaned = Planner._remove_unstated_years("2018년 이후 시험", plan)
    assert cleaned.filters.start_year == 2018
    assert cleaned.filters.end_year is None
    assert cleaned.assumptions == []


def test_flat_request_builds_explicit_filters():
    request = QueryRequest(
        query="단계별로 보여줘",
        condition="lung cancer",
        interventions=["Pembrolizumab"],
        start_year=2018,
        phases=["phase 2"],
    )
    filters = request.explicit_filters()
    assert filters is not None
    assert filters.condition == "lung cancer"
    assert filters.interventions == ["Pembrolizumab"]
    assert filters.start_year == 2018
    assert filters.phases == ["PHASE2"]


def test_clinicaltrials_api_calls_are_logged_with_response_items(tmp_path):
    def handler(request):
        if request.url.path.endswith("/studies"):
            return httpx.Response(200, json={"studies": RAW[:2], "totalCount": 2})
        return httpx.Response(200, json={"apiVersion": "test", "dataTimestamp": "now"})

    async def run():
        http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://clinicaltrials.test/api/v2"
        )
        client = ClinicalTrialsClient(client=http)
        audit = AuditRun({"query": "test"}, str(tmp_path))
        plan = AnalysisPlan(
            filters=Filters(condition="lung cancer"),
            analyses=[AnalysisTask(
                id="phase", type=AnalysisType.DISTRIBUTION, group_by=[Dimension.PHASE]
            )],
        )
        await client.search(plan, audit=audit)
        await client.get_version(audit=audit)
        audit.complete({"ok": True})
        await http.aclose()

    asyncio.run(run())
    record = json.loads(next(tmp_path.glob("*.jsonl")).read_text(encoding="utf-8"))
    assert len(record["api_calls"]) == 2
    studies_call = record["api_calls"][0]
    assert studies_call["path"] == "/studies"
    assert studies_call["params"]["query.cond"] == "lung cancer"
    assert studies_call["request"]["params"]["query.cond"] == "lung cancer"
    assert "query.cond=lung%20cancer" in studies_call["request"]["url"]
    assert studies_call["request"]["query_string"]
    assert studies_call["request"]["replay_curl"].startswith("curl -fsS")
    assert studies_call["attempt"] == 1
    assert studies_call["response"]["study_count"] == 2
    assert studies_call["response"]["items"][0]["nct_id"] == "NCT00000001"


def test_detail_api_fetch_is_bounded_deduplicated_and_logged(tmp_path, monkeypatch):
    import app.clinicaltrials as clinical_module

    monkeypatch.setattr(
        clinical_module, "settings",
        SimpleNamespace(detail_fetch_limit=2, detail_fetch_concurrency=2),
    )

    def handler(request):
        nct_id = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=raw_study(
            nct_id, 2020, "PHASE2", "Pembrolizumab", "Sponsor A"
        ))

    async def run():
        http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://clinicaltrials.test/api/v2"
        )
        client = ClinicalTrialsClient(client=http)
        audit = AuditRun({"query": "detail"}, str(tmp_path))
        details, meta = await client.get_studies_detail(
            ["NCT00000001", "NCT00000001", "NCT00000002", "NCT00000003"], audit=audit
        )
        audit.complete({"ok": True})
        await http.aclose()
        return details, meta

    details, meta = asyncio.run(run())
    assert set(details) == {"NCT00000001", "NCT00000002"}
    assert meta["requested_count"] == 3
    assert meta["retrieved_count"] == 2
    assert meta["truncated"] is True
    record = json.loads(next(tmp_path.glob("*.jsonl")).read_text(encoding="utf-8"))
    assert all(call["path"].startswith("/studies/NCT") for call in record["api_calls"])
    assert record["api_calls"][0]["response"]["study_count"] == 1
    assert record["api_calls"][0]["response"]["modules"]


def test_monitoring_repository_reads_jsonl(tmp_path, monkeypatch):
    import app.monitoring as monitoring_module

    monkeypatch.setattr(monitoring_module, "settings", SimpleNamespace(audit_log_dir=str(tmp_path)))
    audit = AuditRun({"query": "모니터링 테스트"}, str(tmp_path))
    audit.add_api_call(
        method="GET", path="/studies", url="https://example.test/studies",
        params={"query.cond": "cancer"}, status_code=200, duration_ms=120,
        response={"study_count": 1, "items": [{"nct_id": "NCT00000001"}]},
    )
    audit.complete({"records_retrieved": 1, "records_used": 1, "visualizations": []})

    runs = list_runs()
    assert len(runs) == 1
    assert runs[0]["query"] == "모니터링 테스트"
    assert runs[0]["duration_ms"] == 120
    assert runs[0]["request_params"]["query.cond"] == "cancer"
    assert dashboard_stats(runs)["success_rate"] == 100.0
    detail = get_run(runs[0]["request_id"])
    assert detail is not None
    assert detail["api_calls"][0]["response"]["study_count"] == 1


def test_plan_rejects_unknown_fields_and_invalid_semantics():
    with pytest.raises(ValidationError):
        Filters(condition="lung cancer", invented_filter=True)
    with pytest.raises(ValidationError):
        AnalysisTask(
            id="bad_trend", type=AnalysisType.TIME_TREND, group_by=[Dimension.SPONSOR]
        )
    with pytest.raises(ValidationError):
        AnalysisTask(
            id="bad_comparison", type=AnalysisType.COMPARISON, group_by=[Dimension.PHASE]
        )


def test_llm_visualization_selects_allowed_chart_without_changing_data():
    class FakeCompletions:
        async def create(self, **kwargs):
            arguments = json.dumps({
                "type": "time_series",
                "title": "연도별 임상시험 추세",
                "encoding": {
                    "x": {"field": "year", "type": "temporal"},
                    "y": {"field": "trial_count", "type": "quantitative"},
                },
                "metadata": {"time_granularity": "year"},
            })
            call = SimpleNamespace(function=SimpleNamespace(arguments=arguments))
            message = SimpleNamespace(tool_calls=[call])
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    builder = VisualizationBuilder(client=fake_client)
    task = AnalysisTask(
        id="trend", type=AnalysisType.TIME_TREND, group_by=[Dimension.YEAR]
    )
    result = aggregate(normalize_many(RAW), task)
    visualization = asyncio.run(builder.build("연도별 추세", task, result))
    assert visualization.type == "time_series"
    assert visualization.metadata["design_source"] == "llm"
    assert [item.dict(exclude_none=True) for item in visualization.data] == result["rows"]


def test_visualization_contract_rejects_unknown_encoding_channels():
    with pytest.raises(ValidationError):
        Visualization.parse_obj({
            "id": "invalid", "type": "bar_chart", "title": "Invalid",
            "encoding": {"radius": {"field": "trial_count"}},
            "data": [{
                "phase": "PHASE2", "trial_count": 1, "source_count": 1,
                "citations_truncated": False, "citations": [],
            }],
        })


def test_checked_in_example_outputs_match_public_response_schema():
    example_dir = Path(__file__).parents[1] / "examples"
    paths = sorted(example_dir.glob("*.json"))
    assert len(paths) == 3
    for path in paths:
        QueryResponse.parse_obj(json.loads(path.read_text(encoding="utf-8")))
