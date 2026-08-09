import json
import re
from typing import Optional

from openai import AsyncOpenAI

from app.config import settings
from app.models import AnalysisPlan, AnalysisTask, AnalysisType, Dimension, Filters


PLAN_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_analysis_plan",
        "description": "Return a constrained plan for ClinicalTrials.gov analysis.",
        "parameters": AnalysisPlan.schema(),
    },
}


SYSTEM_PROMPT = """You plan analyses over ClinicalTrials.gov study records.
Extract filters conservatively. Never invent a drug, disease, sponsor, country, year, or status.
condition is only a disease or medical condition. interventions are only drugs, biologics,
devices, procedures, or treatments. Do not narrow a broad disease to an unstated subtype.
Translate non-English medical conditions and generic treatment terms into standard English terms
used for ClinicalTrials.gov search (for example, 폐암 -> lung cancer). Preserve official drug and
sponsor names with their conventional English spelling. This is normalization, not an assumption;
never add a concept that the user did not state.
Set a year only when that exact year is explicitly present in the user's question. Do not insert
the current year as end_year. Records missing a group-by dimension are excluded by the current
aggregation engine; never claim they will be placed in an Unknown bucket.
Explicit structured fields are authoritative user inputs: preserve them exactly and use them when
choosing analysis type and group_by. A time_trend requires year. A comparison requires at least
two group_by dimensions. A network requires exactly two group_by dimensions.
Use only the supplied schema. A comparison between named interventions should keep them in
filters.interventions and group by intervention plus the compared dimension. Use year for trends,
phase/status/intervention_type/country for distributions, sponsor/country for rankings, and
[sponsor, intervention] or [intervention, intervention] for networks. Add assumptions only when
you apply an explicit interpretation. Always call submit_analysis_plan exactly once."""


class Planner:
    """Create schema-validated plans with an LLM or a limited local fallback."""

    def __init__(self, client: Optional[AsyncOpenAI] = None) -> None:
        """Use an injected OpenAI client or construct one when a key is configured."""
        self.client = client or (
            AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        )

    async def create_plan(self, query: str, supplied_filters: Optional[Filters]) -> AnalysisPlan:
        """Plan a query, sanitize model output, and give explicit fields precedence."""
        if self.client is None:
            plan = self._rule_based_plan(query)
        else:
            planner_input = {
                "natural_language_query": query,
                "explicit_structured_fields": supplied_filters.dict(exclude_none=True)
                if supplied_filters else {},
            }
            response = await self.client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(planner_input, ensure_ascii=False)},
                ],
                tools=[PLAN_TOOL],
                tool_choice={"type": "function", "function": {"name": "submit_analysis_plan"}},
            )
            call = response.choices[0].message.tool_calls[0]
            plan = AnalysisPlan.parse_obj(json.loads(call.function.arguments))

        plan = self._remove_unstated_years(query, plan)

        if supplied_filters:
            merged = plan.filters.dict()
            for key, value in supplied_filters.dict().items():
                if value not in (None, [], ""):
                    merged[key] = value
            plan.filters = Filters(**merged)
        return plan

    @staticmethod
    def _remove_unstated_years(query: str, plan: AnalysisPlan) -> AnalysisPlan:
        """Prevent the model from silently introducing an unstated date boundary."""
        stated_years = {int(value) for value in re.findall(r"(?:19|20)\d{2}", query)}
        if plan.filters.start_year is not None and plan.filters.start_year not in stated_years:
            plan.filters.start_year = None
        if plan.filters.end_year is not None and plan.filters.end_year not in stated_years:
            plan.filters.end_year = None
        plan.assumptions = [
            item for item in plan.assumptions
            if "unknown" not in item.casefold() and "phase 없음" not in item.casefold()
        ]
        return plan

    def _rule_based_plan(self, query: str) -> AnalysisPlan:
        """Provide a small deterministic fallback for development without an API key."""
        lower = query.lower()
        years = [int(value) for value in re.findall(r"(?:19|20)\d{2}", query)]
        filters = Filters(
            start_year=min(years) if years else None,
            end_year=max(years) if len(years) > 1 else None,
            overall_statuses=["RECRUITING"] if "모집 중" in query or "recruiting" in lower else [],
        )

        if "연도" in query or "추세" in query or "시간" in query or "over time" in lower:
            task = AnalysisTask(id="time_trend", type=AnalysisType.TIME_TREND, group_by=[Dimension.YEAR])
        elif "스폰서" in query or "sponsor" in lower:
            task = AnalysisTask(
                id="sponsor_ranking", type=AnalysisType.RANKING,
                group_by=[Dimension.SPONSOR], limit=10,
            )
        elif "네트워크" in query or "network" in lower or "관계" in query:
            task = AnalysisTask(
                id="relationship_network", type=AnalysisType.NETWORK,
                group_by=[Dimension.SPONSOR, Dimension.INTERVENTION], limit=50,
            )
        else:
            task = AnalysisTask(
                id="phase_distribution", type=AnalysisType.DISTRIBUTION,
                group_by=[Dimension.PHASE],
            )

        return AnalysisPlan(
            filters=filters,
            analyses=[task],
            assumptions=["OPENAI_API_KEY가 없어 제한된 규칙 기반 플래너를 사용했습니다."],
        )
"""Constrained LLM planner that translates user intent into an executable analysis plan."""
