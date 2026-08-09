"""Application service that orchestrates one complete query-agent run."""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.analysis import aggregate
from app.audit import AuditRun
from app.clinicaltrials import ClinicalTrialsClient
from app.config import settings
from app.models import QueryRequest, QueryResponse
from app.normalizer import apply_exact_filters, normalize_many
from app.planner import Planner
from app.visualization import VisualizationBuilder


class QueryService:
    """Coordinate planning, retrieval, aggregation, visualization, and auditing."""

    def __init__(
        self, planner: Optional[Planner] = None,
        clinical_trials: Optional[ClinicalTrialsClient] = None,
        visualization_builder: Optional[VisualizationBuilder] = None,
    ) -> None:
        """Accept injectable collaborators so the pipeline stays easy to test."""
        self.planner = planner or Planner()
        self.clinical_trials = clinical_trials or ClinicalTrialsClient()
        self.visualization_builder = visualization_builder or VisualizationBuilder()

    async def close(self) -> None:
        """Release resources owned by the external API client."""
        await self.clinical_trials.close()

    async def execute(self, request: QueryRequest) -> QueryResponse:
        """Execute a validated query request and persist a replayable audit record."""
        audit = AuditRun(request.dict(), settings.audit_log_dir)
        trace = []
        try:
            plan = await self.planner.create_plan(request.query, request.explicit_filters())
            audit.set_plan(plan.dict())
            audit.add_pipeline_event("create_plan", status="success")
            trace.append({"step": 1, "action": "create_plan", "status": "success"})

            raw_studies, retrieval_meta = await self.clinical_trials.search(plan, audit=audit)
            audit.add_pipeline_event("search_trials", status="success", records=len(raw_studies))
            trace.append({
                "step": 2, "action": "search_trials", "status": "success",
                "records": len(raw_studies),
            })

            normalized = normalize_many(raw_studies)
            filtered = apply_exact_filters(normalized, plan.filters)
            audit.add_pipeline_event(
                "normalize_and_filter", status="success", records=len(filtered),
                excluded=len(normalized) - len(filtered),
            )
            trace.append({
                "step": 3, "action": "normalize_and_filter", "status": "success",
                "records": len(filtered), "excluded": len(normalized) - len(filtered),
            })

            aggregate_results = []
            for task in plan.analyses:
                result = aggregate(filtered, task, plan.filters.interventions)
                aggregate_results.append(result)
                audit.add_pipeline_event(
                    "aggregate_and_build", analysis_id=task.id, status="success",
                    output_rows=_result_size(result),
                )
                trace.append({
                    "step": len(trace) + 1, "action": "aggregate_and_build",
                    "analysis_id": task.id, "status": "success",
                })

            detail_meta = {
                "requested_count": 0, "retrieved_count": 0,
                "limit": getattr(settings, "detail_fetch_limit", 50),
                "truncated": False, "nct_ids": [], "strategy": "on_demand",
            }

            visualizations = []
            for task, result in zip(plan.analyses, aggregate_results):
                visualization = await self.visualization_builder.build(request.query, task, result)
                if not request.include_citations:
                    _remove_citations(visualization.data)
                visualizations.append(visualization)
                audit.add_pipeline_event(
                    "design_visualization", status="success", analysis_id=task.id,
                    chart_type=visualization.type,
                    design_source=visualization.metadata.get("design_source"),
                )
                trace.append({
                    "step": len(trace) + 1, "action": "design_visualization",
                    "analysis_id": task.id, "status": "success",
                    "chart_type": visualization.type,
                    "design_source": visualization.metadata.get("design_source"),
                })

            version = await self.clinical_trials.get_version(audit=audit)
            truncated = any(item.get("truncated") for item in retrieval_meta["requests"])
            if truncated:
                raise RuntimeError("Search exceeded MAX_PAGES; refusing to return partial statistics")

            response = QueryResponse(
                query=request.query,
                plan=plan,
                visualizations=visualizations,
                meta={
                    "request_id": audit.request_id,
                    "audit_log": f"{settings.audit_log_dir}/{audit.record['started_at'][:10]}.jsonl",
                    "source": "ClinicalTrials.gov",
                    "api_version": version.get("apiVersion"),
                    "data_timestamp": version.get("dataTimestamp"),
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "records_retrieved": len(raw_studies),
                    "records_used": len(filtered),
                    "retrieval": retrieval_meta,
                    "detail_retrieval": detail_meta,
                    "agent_trace": trace,
                },
            )
            audit.set_response_output(response.dict())
            audit.complete({
                "records_retrieved": len(raw_studies),
                "records_used": len(filtered),
                "visualizations": [
                    {"id": item.id, "type": item.type, "data_items": len(item.data)}
                    for item in visualizations
                ],
            })
            return response
        except Exception as exc:
            audit.fail(exc)
            raise


def _result_size(result: Dict[str, Any]) -> int:
    """Return a stable output-size metric for tabular and network aggregates."""
    if result.get("kind") == "network":
        return len(result.get("edges", []))
    return len(result.get("rows", []))


def _remove_citations(value: Any) -> None:
    """Remove nested citation arrays in place when the caller opts out."""
    if isinstance(value, list):
        for item in value:
            _remove_citations(item)
    elif isinstance(value, dict):
        value.pop("citations", None)
        for item in value.values():
            _remove_citations(item)
