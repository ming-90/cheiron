from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, root_validator, validator


class StrictModel(BaseModel):
    """Base model that rejects fields outside the documented contract."""

    class Config:
        extra = "forbid"


class AnalysisType(str, Enum):
    """Deterministic aggregation algorithms the planner may select."""
    TIME_TREND = "time_trend"
    DISTRIBUTION = "distribution"
    COMPARISON = "comparison"
    RANKING = "ranking"
    NETWORK = "network"


class Dimension(str, Enum):
    """Normalized study dimensions supported by the aggregation engine."""
    YEAR = "year"
    PHASE = "phase"
    STATUS = "status"
    INTERVENTION = "intervention"
    INTERVENTION_TYPE = "intervention_type"
    SPONSOR = "sponsor"
    SPONSOR_CLASS = "sponsor_class"
    COUNTRY = "country"


class Filters(StrictModel):
    """Canonical filters shared by planner output and retrieval code."""
    condition: Optional[str] = Field(
        None, description=(
            "사용자가 명시한 질환 또는 의학적 상태. ClinicalTrials.gov 검색에 적합한 "
            "영어 의학 용어로 정규화한다. 약물·국가·스폰서는 넣지 않는다."
        )
    )
    interventions: List[str] = Field(
        default_factory=list,
        description=(
            "사용자가 명시한 약물, 생물학적 제제, 기기, 시술 또는 치료 목록. "
            "ClinicalTrials.gov에서 검색 가능한 공식 영문명으로 정규화한다."
        ),
    )
    sponsor: Optional[str] = Field(None, description="연구 대표 스폰서 또는 협력기관 이름.")
    country: Optional[str] = Field(None, description="임상시험 수행 국가의 표준 영어 이름.")
    overall_statuses: List[str] = Field(
        default_factory=list, description="명시된 모집·진행 상태의 ClinicalTrials.gov enum 목록."
    )
    phases: List[str] = Field(
        default_factory=list, description="명시된 임상 단계 enum 목록. 예: PHASE1, PHASE2."
    )
    study_types: List[str] = Field(
        default_factory=list, description="연구 유형 enum 목록. 예: INTERVENTIONAL, OBSERVATIONAL."
    )
    start_year: Optional[int] = Field(
        None, ge=1900, le=2200,
        description="포함할 최소 연구 시작 연도. 질문에 정확한 연도가 있을 때만 설정한다.",
    )
    end_year: Optional[int] = Field(
        None, ge=1900, le=2200,
        description="포함할 최대 연구 시작 연도. 질문에 정확한 연도가 있을 때만 설정한다.",
    )

    @validator("overall_statuses", "study_types", pre=True, each_item=True)
    def uppercase_enums(cls, value: str) -> str:
        """Normalize status and study-type enum spelling."""
        return value.upper().replace(" ", "_")

    @validator("phases", pre=True, each_item=True)
    def normalize_phases(cls, value: str) -> str:
        """Normalize phase variants such as `phase 2` to `PHASE2`."""
        return value.upper().replace(" ", "").replace("_", "")

    @validator("end_year")
    def validate_year_range(cls, value: Optional[int], values: Dict[str, Any]) -> Optional[int]:
        """Reject an end year that precedes the start year."""
        start = values.get("start_year")
        if value is not None and start is not None and value < start:
            raise ValueError("end_year must be greater than or equal to start_year")
        return value


class AnalysisTask(StrictModel):
    """One validated aggregation requested by an analysis plan."""
    id: str = Field(..., description="응답 안에서 분석 작업을 식별하는 고유 이름.")
    type: AnalysisType = Field(..., description="허용된 분석 실행 유형.")
    group_by: List[Dimension] = Field(
        ..., min_items=1, description="집계 결과를 그룹화할 허용된 차원 목록."
    )
    limit: Optional[int] = Field(None, ge=1, le=100, description="순위나 노드/엣지 최대 개수.")
    minimum_weight: int = Field(1, ge=1, description="네트워크에 포함할 최소 고유 연구 수.")

    @root_validator
    def validate_analysis_semantics(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """Enforce group-by requirements that JSON types alone cannot express."""
        analysis_type = values.get("type")
        group_by = values.get("group_by") or []
        if analysis_type == AnalysisType.TIME_TREND and Dimension.YEAR not in group_by:
            raise ValueError("time_trend requires year in group_by")
        if analysis_type == AnalysisType.COMPARISON and len(group_by) < 2:
            raise ValueError("comparison requires at least two group_by dimensions")
        if analysis_type == AnalysisType.NETWORK and len(group_by) != 2:
            raise ValueError("network requires exactly two group_by dimensions")
        if analysis_type != AnalysisType.NETWORK and len(group_by) != len(set(group_by)):
            raise ValueError("duplicate group_by dimensions are only valid for networks")
        return values


class AnalysisPlan(StrictModel):
    """Complete, executable output of the constrained planner."""
    filters: Filters
    analyses: List[AnalysisTask] = Field(..., min_items=1, max_items=5)
    assumptions: List[str] = Field(default_factory=list)


class QueryRequest(StrictModel):
    """Public flat request schema; only `query` is required."""
    query: str = Field(..., min_length=3, max_length=2000)
    condition: Optional[str] = None
    interventions: List[str] = Field(default_factory=list)
    sponsor: Optional[str] = None
    country: Optional[str] = None
    overall_statuses: List[str] = Field(default_factory=list)
    phases: List[str] = Field(default_factory=list)
    study_types: List[str] = Field(default_factory=list)
    start_year: Optional[int] = Field(None, ge=1900, le=2200)
    end_year: Optional[int] = Field(None, ge=1900, le=2200)
    include_citations: bool = True

    @validator("overall_statuses", "study_types", pre=True, each_item=True)
    def uppercase_request_enums(cls, value: str) -> str:
        """Normalize enum-like values supplied directly by API callers."""
        return value.upper().replace(" ", "_")

    @validator("phases", pre=True, each_item=True)
    def normalize_request_phases(cls, value: str) -> str:
        """Normalize direct request phase values before planner merging."""
        return value.upper().replace(" ", "").replace("_", "")

    @validator("end_year")
    def validate_request_year_range(
        cls, value: Optional[int], values: Dict[str, Any]
    ) -> Optional[int]:
        """Validate the request-level year interval."""
        start = values.get("start_year")
        if value is not None and start is not None and value < start:
            raise ValueError("end_year must be greater than or equal to start_year")
        return value

    def explicit_filters(self) -> Optional[Filters]:
        """Return only caller-supplied filters, or `None` when all are empty."""
        values = {
            "condition": self.condition,
            "interventions": self.interventions,
            "sponsor": self.sponsor,
            "country": self.country,
            "overall_statuses": self.overall_statuses,
            "phases": self.phases,
            "study_types": self.study_types,
            "start_year": self.start_year,
            "end_year": self.end_year,
        }
        if all(value in (None, [], "") for value in values.values()):
            return None
        return Filters(**values)


class Citation(StrictModel):
    """Source record and field that support one visualization value."""
    nct_id: str
    field_path: str
    value: Any
    source_url: str
    title: Optional[str] = None
    evidence: List["CitationEvidence"] = Field(default_factory=list)


class CitationEvidence(StrictModel):
    """One exact ClinicalTrials.gov field/value supporting a grouped datum."""
    field_path: str
    value: Any


class TabularDatum(StrictModel):
    """One supported tabular aggregate row."""
    year: Optional[int] = None
    phase: Optional[str] = None
    status: Optional[str] = None
    intervention: Optional[str] = None
    intervention_type: Optional[str] = None
    sponsor: Optional[str] = None
    sponsor_class: Optional[str] = None
    country: Optional[str] = None
    trial_count: int = Field(..., ge=0)
    citations: List[Citation] = Field(default_factory=list)
    source_count: int = Field(..., ge=0)
    citations_truncated: bool = False


class NetworkNode(StrictModel):
    """One network entity whose size represents a distinct-NCT count."""
    id: str
    group: str
    trial_count: int = Field(..., ge=0)
    citations: List[Citation] = Field(default_factory=list)
    source_count: int = Field(..., ge=0)
    citations_truncated: bool = False


class NetworkEdge(StrictModel):
    """One weighted relationship backed by distinct source studies."""
    source: str
    target: str
    weight: int = Field(..., ge=1)
    citations: List[Citation] = Field(default_factory=list)
    source_count: int = Field(..., ge=0)
    citations_truncated: bool = False


class NetworkDatum(StrictModel):
    """Complete node/edge payload for a network visualization."""
    nodes: List[NetworkNode]
    edges: List[NetworkEdge]


class EncodingField(StrictModel):
    """Field-to-channel mapping understood by the frontend adapter."""
    field: str
    type: Optional[str] = None
    aggregate: Any = None
    sort: Any = None
    title: Optional[str] = None
    format: Optional[str] = None
    axis: Optional[Dict[str, Any]] = None
    legend: Optional[Dict[str, Any]] = None


class NetworkNodeEncoding(StrictModel):
    """Network node field mappings."""
    id: str
    group: str
    size: str


class NetworkEdgeEncoding(StrictModel):
    """Network edge field mappings."""
    source: str
    target: str
    weight: str


class MarkEncoding(StrictModel):
    """Optional renderer-neutral mark hints returned by the designer."""
    type: Optional[str] = None
    grouping: Optional[str] = None


class VisualizationEncoding(StrictModel):
    """Supported visual channels for tabular and network charts."""
    x: Optional[EncodingField] = None
    y: Optional[EncodingField] = None
    series: Optional[EncodingField] = None
    color: Optional[EncodingField] = None
    text: Optional[EncodingField] = None
    tooltip: List[EncodingField] = Field(default_factory=list)
    nodes: Optional[NetworkNodeEncoding] = None
    edges: Optional[NetworkEdgeEncoding] = None
    mark: Optional[Union[str, MarkEncoding]] = None
    orientation: Optional[str] = None


class VisualizationMetadata(BaseModel):
    """Documented metadata plus safe designer-specific display hints."""
    metric: str = "distinct_nct_id_count"
    design_source: Optional[str] = None
    candidate_chart_types: List[str] = Field(default_factory=list)
    citation_policy: Optional[str] = None
    minimum_weight: Optional[int] = None
    unit: Optional[str] = None
    sort_order: Optional[str] = None
    description: Optional[str] = None
    note: Optional[str] = None

    class Config:
        extra = "allow"

    def get(self, key: str, default: Any = None) -> Any:
        """Provide the small mapping interface used by orchestration code."""
        return getattr(self, key, default)

    def update(self, values: Dict[str, Any]) -> None:
        """Apply validated or designer-specific metadata values in place."""
        for key, value in values.items():
            setattr(self, key, value)

    def __getitem__(self, key: str) -> Any:
        """Read metadata with dictionary syntax for backward compatibility."""
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        """Set metadata with dictionary syntax for injected test builders."""
        setattr(self, key, value)


class Visualization(StrictModel):
    """Renderer-independent chart specification returned to the frontend."""
    id: str
    type: str
    title: str
    encoding: VisualizationEncoding
    data: Union[List[TabularDatum], List[NetworkDatum]]
    metadata: VisualizationMetadata = Field(default_factory=VisualizationMetadata)


class VisualizationDesign(StrictModel):
    """LLM-selected presentation fields; verified data is attached by code."""

    type: str = Field(..., description="One chart type from the supplied candidates.")
    title: str = Field(..., min_length=1, max_length=200)
    encoding: Dict[str, Any] = Field(
        ..., description="Frontend visual-channel mapping using only supplied data fields."
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)


class QueryResponse(StrictModel):
    """Public response containing plan, charts, and retrieval metadata."""
    query: str
    plan: AnalysisPlan
    visualizations: List[Visualization]
    meta: "ResponseMetadata"


class RetrievalRequestMetadata(StrictModel):
    """Summary of one compiled paginated ClinicalTrials.gov search."""
    query_params: Dict[str, Any]
    fields: List[str]
    pages: int = Field(..., ge=0)
    retrieved_count: int = Field(..., ge=0)
    total_count: Optional[int] = Field(None, ge=0)
    truncated: bool


class RetrievalMetadata(StrictModel):
    """All search requests used for one query."""
    requests: List[RetrievalRequestMetadata]


class DetailRetrievalMetadata(StrictModel):
    """Explicit detail-fetch policy and counters."""
    requested_count: int = Field(..., ge=0)
    retrieved_count: int = Field(..., ge=0)
    limit: int = Field(..., ge=1)
    truncated: bool
    nct_ids: List[str]
    strategy: str


class AgentTraceEvent(BaseModel):
    """One ordered, extensible pipeline trace event."""
    step: int = Field(..., ge=1)
    action: str
    status: str

    class Config:
        extra = "allow"


class ResponseMetadata(StrictModel):
    """Frontend- and audit-relevant metadata returned with every query."""
    request_id: str
    audit_log: str
    source: str
    api_version: Optional[str] = None
    data_timestamp: Optional[str] = None
    retrieved_at: str
    records_retrieved: int = Field(..., ge=0)
    records_used: int = Field(..., ge=0)
    retrieval: RetrievalMetadata
    detail_retrieval: DetailRetrievalMetadata
    agent_trace: List[AgentTraceEvent]


class NormalizedStudy(StrictModel):
    """Stable subset of a ClinicalTrials.gov record used by the engine."""
    nct_id: str
    title: Optional[str] = None
    start_date: Optional[str] = None
    start_year: Optional[int] = None
    overall_status: Optional[str] = None
    phases: List[str] = Field(default_factory=list)
    study_type: Optional[str] = None
    enrollment: Optional[int] = None
    conditions: List[str] = Field(default_factory=list)
    interventions: List[Dict[str, str]] = Field(default_factory=list)
    sponsor: Optional[str] = None
    sponsor_class: Optional[str] = None
    countries: List[str] = Field(default_factory=list)
    raw: Dict[str, Any] = Field(default_factory=dict, exclude=True)


Citation.update_forward_refs(CitationEvidence=CitationEvidence)
QueryResponse.update_forward_refs(ResponseMetadata=ResponseMetadata)
"""Strict request, plan, study, citation, and visualization data contracts."""
