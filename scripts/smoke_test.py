"""Run a small real-API pipeline without invoking OpenAI."""

import asyncio
import json
import sys
from pathlib import Path


# Support the documented `python3 scripts/smoke_test.py` invocation by making
# the repository root importable when Python starts from the scripts directory.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.analysis import aggregate
from app.clinicaltrials import ClinicalTrialsClient
from app.models import AnalysisPlan, AnalysisTask, AnalysisType, Dimension, Filters
from app.normalizer import apply_exact_filters, normalize_many
from app.visualization import build_visualization


async def main() -> None:
    client = ClinicalTrialsClient()
    try:
        plan = AnalysisPlan(
            filters=Filters(condition="COVID-19", start_year=2024),
            analyses=[
                AnalysisTask(
                    id="phase_distribution",
                    type=AnalysisType.DISTRIBUTION,
                    group_by=[Dimension.PHASE],
                    limit=5,
                )
            ],
        )
        raw, retrieval = await client.search(plan)
        studies = apply_exact_filters(normalize_many(raw), plan.filters)
        result = aggregate(studies, plan.analyses[0])
        visualization = build_visualization(plan.analyses[0], result)
        print(json.dumps({
            "records_retrieved": len(raw),
            "records_used": len(studies),
            "retrieval": retrieval,
            "visualization": visualization.dict(exclude_none=True),
        }, ensure_ascii=False, indent=2))
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
