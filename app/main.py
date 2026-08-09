from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.models import QueryRequest, QueryResponse
from app.monitoring import dashboard_stats, get_run, list_runs
from app.service import QueryService


service = QueryService()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Close shared outbound clients when FastAPI shuts down."""
    yield
    await service.close()


app = FastAPI(
    title="ClinicalTrials.gov Query-to-Visualization Agent",
    version="0.1.0",
    lifespan=lifespan,
)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def root():
    """Serve the bundled single-page application."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    """Serve the same application at its explicit dashboard route."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
async def health():
    """Return a lightweight liveness response."""
    return {"status": "ok"}


@app.get("/v1/monitoring/runs")
async def monitoring_runs(
    limit: int = Query(50, ge=1, le=500),
    status: Optional[str] = Query(None, regex="^(success|error)$"),
):
    """Return recent run summaries and dashboard statistics."""
    runs = list_runs(limit=limit, status=status)
    return {"stats": dashboard_stats(runs), "runs": runs}


@app.get("/v1/monitoring/runs/{request_id}")
async def monitoring_run(request_id: str):
    """Return one complete, replayable audit record."""
    run = get_run(request_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.post("/v1/query", response_model=QueryResponse, response_model_exclude_none=True)
async def query(request: QueryRequest) -> QueryResponse:
    """Execute the query agent and translate expected failures to HTTP errors."""
    try:
        return await service.execute(request)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"ClinicalTrials.gov returned HTTP {exc.response.status_code}",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="ClinicalTrials.gov is unavailable") from exc
    except (ValueError, IndexError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/v1/studies/{nct_id}")
async def study_detail(nct_id: str) -> Dict[str, Any]:
    """Validate an NCT ID and proxy its on-demand full study record."""
    normalized = nct_id.upper()
    if not normalized.startswith("NCT") or len(normalized) != 11 or not normalized[3:].isdigit():
        raise HTTPException(status_code=422, detail="nct_id must match NCT followed by 8 digits")
    try:
        return await service.clinical_trials.get_study(normalized)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Study not found") from exc
        raise HTTPException(status_code=502, detail="ClinicalTrials.gov request failed") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="ClinicalTrials.gov is unavailable") from exc
"""FastAPI entry point for queries, monitoring, details, and the bundled frontend."""
