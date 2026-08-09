import json
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from app.config import settings
from app.models import AnalysisTask, Visualization, VisualizationDesign


LABELS = {
    "year": "연도",
    "phase": "임상 단계",
    "status": "모집 상태",
    "intervention": "중재",
    "intervention_type": "중재 유형",
    "sponsor": "스폰서",
    "sponsor_class": "스폰서 분류",
    "country": "국가",
}

VISUALIZATION_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_visualization_design",
        "description": "Choose a frontend-renderable chart design for verified aggregate data.",
        "parameters": VisualizationDesign.schema(),
    },
}

VISUALIZATION_PROMPT = """You design a visualization for verified ClinicalTrials.gov aggregates.
Choose exactly one supplied candidate_chart_type. Use only fields in data_fields; never calculate,
rename, add, remove, or alter data values. Return presentation decisions only: chart type, concise
Korean title, encoding, and optional display metadata. Counts use a quantitative channel. Years use
a temporal or ordinal x channel. Rankings normally use horizontal bars. Multi-series comparisons
must identify a series/color field. Network data uses nodes and edges encodings. Always call
submit_visualization_design exactly once."""


class VisualizationBuilder:
    """Ask an LLM for presentation choices while keeping data code-owned and immutable."""

    def __init__(self, client: Optional[AsyncOpenAI] = None) -> None:
        """Use an injected client or initialize one from application settings."""
        self.client = client or (
            AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        )

    async def build(
        self, query: str, task: AnalysisTask, result: Dict[str, Any]
    ) -> Visualization:
        """Select and validate a chart design, falling back deterministically on failure."""
        fallback = build_visualization(task, result)
        candidates = candidate_chart_types(task, result)
        if self.client is None:
            fallback.metadata.update({
                "design_source": "deterministic_fallback",
                "candidate_chart_types": candidates,
            })
            return fallback

        payload = {
            "user_question": query,
            "analysis": task.dict(),
            "candidate_chart_types": candidates,
            "data_fields": _data_fields(result),
            "verified_aggregate_data": result,
        }
        try:
            response = await self.client.chat.completions.create(
                model=settings.visualization_model,
                messages=[
                    {"role": "system", "content": VISUALIZATION_PROMPT},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                tools=[VISUALIZATION_TOOL],
                tool_choice={
                    "type": "function",
                    "function": {"name": "submit_visualization_design"},
                },
            )
            call = response.choices[0].message.tool_calls[0]
            design = VisualizationDesign.parse_obj(json.loads(call.function.arguments))
            if design.type not in candidates:
                raise ValueError(f"unsupported chart selection: {design.type}")
            _validate_encoding_fields(design.encoding, set(payload["data_fields"]))
            metadata = dict(design.metadata)
            metadata.update({
                "metric": "distinct_nct_id_count",
                "design_source": "llm",
                "candidate_chart_types": candidates,
            })
            return Visualization(
                id=task.id, type=design.type, title=design.title,
                encoding=design.encoding, data=fallback.data, metadata=metadata,
            )
        except Exception as exc:
            fallback.metadata.update({
                "design_source": "deterministic_fallback",
                "design_fallback_reason": type(exc).__name__,
                "candidate_chart_types": candidates,
            })
            return fallback


def candidate_chart_types(task: AnalysisTask, result: Dict[str, Any]) -> List[str]:
    """Return only chart types compatible with the aggregate's semantic shape."""
    if result["kind"] == "network":
        return ["network_graph"]
    if task.type.value == "time_trend":
        return ["time_series", "bar_chart"]
    if task.type.value == "ranking":
        return ["horizontal_bar_chart", "bar_chart"]
    if len(task.group_by) > 1:
        return ["grouped_bar_chart", "bar_chart"]
    return ["bar_chart", "horizontal_bar_chart"]


def _data_fields(result: Dict[str, Any]) -> List[str]:
    """List fields the visualization model may reference in its encoding."""
    if result["kind"] == "network":
        return ["id", "group", "trial_count", "source", "target", "weight"]
    fields = set()
    for row in result.get("rows", []):
        fields.update(key for key in row if key != "citations")
    return sorted(fields)


def _validate_encoding_fields(value: Any, allowed: set) -> None:
    """Recursively reject encodings that reference fields absent from verified data."""
    if isinstance(value, dict):
        field = value.get("field")
        if field is not None and field not in allowed:
            raise ValueError(f"encoding references unknown field: {field}")
        for nested in value.values():
            _validate_encoding_fields(nested, allowed)
    elif isinstance(value, list):
        for nested in value:
            _validate_encoding_fields(nested, allowed)


def build_visualization(task: AnalysisTask, result: Dict[str, Any]) -> Visualization:
    """Build a deterministic visualization used as fallback and trusted data carrier."""
    dimensions = [dimension.value for dimension in task.group_by]
    if result["kind"] == "network":
        source, target = dimensions[:2]
        return Visualization(
            id=task.id,
            type="network_graph",
            title=f"{LABELS[source]}–{LABELS[target]} 관계 네트워크",
            encoding={
                "nodes": {"id": "id", "group": "group", "size": "trial_count"},
                "edges": {"source": "source", "target": "target", "weight": "weight"},
            },
            data=[{"nodes": result["nodes"], "edges": result["edges"]}],
            metadata={"metric": "distinct_nct_id_count", "minimum_weight": task.minimum_weight},
        )

    chart_type = "bar_chart"
    if task.type.value == "time_trend":
        chart_type = "time_series"
    elif len(dimensions) > 1:
        chart_type = "grouped_bar_chart"

    x_field = dimensions[-1]
    encoding: Dict[str, Any] = {
        "x": {"field": x_field, "type": "temporal" if x_field == "year" else "nominal"},
        "y": {"field": "trial_count", "type": "quantitative", "aggregate": None},
    }
    if len(dimensions) > 1:
        encoding["series"] = {"field": dimensions[0], "type": "nominal"}
    if task.type.value == "ranking":
        encoding = {
            "x": {"field": "trial_count", "type": "quantitative", "aggregate": None},
            "y": {"field": x_field, "type": "nominal", "sort": "-x"},
        }

    title = " / ".join(LABELS[dimension] for dimension in dimensions) + "별 임상시험 수"
    return Visualization(
        id=task.id,
        type=chart_type,
        title=title,
        encoding=encoding,
        data=result["rows"],
        metadata={
            "metric": "distinct_nct_id_count",
            "citation_policy": "각 datum당 최대 설정 개수의 원본 연구를 포함",
        },
    )
"""Turn verified aggregates into a validated, renderer-independent chart contract."""
