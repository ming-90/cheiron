"""Async ClinicalTrials.gov client with compilation, pagination, retry, and audit hooks."""

import asyncio
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.audit import AuditRun, response_items
from app.config import settings
from app.models import AnalysisPlan


FIELDS = [
    "NCTId", "BriefTitle", "OverallStatus", "StartDate", "Phase", "StudyType",
    "EnrollmentCount", "Condition", "InterventionName", "InterventionType",
    "LeadSponsorName", "LeadSponsorClass", "LocationCountry",
]


class ClinicalTrialsClient:
    """Retrieve study records while keeping request behavior deterministic and observable."""

    def __init__(self, client: Optional[httpx.AsyncClient] = None) -> None:
        """Create a client, or accept an injected client for tests and shared lifecycles."""
        self._external_client = client is not None
        self.client = client or httpx.AsyncClient(
            base_url=settings.clinical_trials_base_url,
            timeout=settings.request_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "Cheiron-ClinicalTrials-Agent/0.1"},
        )

    async def close(self) -> None:
        """Close only the HTTP client created by this instance."""
        if not self._external_client:
            await self.client.aclose()

    async def get_version(self, audit: Optional[AuditRun] = None) -> Dict[str, Any]:
        """Return API version and data timestamp metadata."""
        response = await self._get_with_retry("/version", audit=audit)
        return response.json()

    async def get_study(
        self, nct_id: str, audit: Optional[AuditRun] = None
    ) -> Dict[str, Any]:
        """Fetch the complete record for one NCT identifier."""
        response = await self._get_with_retry(f"/studies/{nct_id}", audit=audit)
        return response.json()

    async def get_studies_detail(
        self, nct_ids: List[str], audit: Optional[AuditRun] = None
    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
        """Fetch selected full records with bounded concurrency and de-duplication."""
        unique_ids = list(dict.fromkeys(nct_ids))
        requested = unique_ids[: settings.detail_fetch_limit]
        semaphore = asyncio.Semaphore(settings.detail_fetch_concurrency)

        async def fetch(nct_id: str) -> Tuple[str, Dict[str, Any]]:
            """Fetch one detail record while respecting the shared concurrency limit."""
            async with semaphore:
                return nct_id, await self.get_study(nct_id, audit=audit)

        outcomes = await asyncio.gather(
            *(fetch(nct_id) for nct_id in requested), return_exceptions=True
        )
        pairs = [outcome for outcome in outcomes if not isinstance(outcome, Exception)]
        failed_ids = [
            nct_id for nct_id, outcome in zip(requested, outcomes)
            if isinstance(outcome, Exception)
        ]
        return dict(pairs), {
            "requested_count": len(unique_ids),
            "retrieved_count": len(pairs),
            "failed_count": len(failed_ids),
            "failed_nct_ids": failed_ids,
            "limit": settings.detail_fetch_limit,
            "truncated": len(unique_ids) > len(requested),
            "nct_ids": requested,
        }

    async def search(
        self, plan: AnalysisPlan, audit: Optional[AuditRun] = None
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Run one paginated search per intervention and deduplicate by NCT ID."""
        interventions = plan.filters.interventions or [None]
        all_studies: Dict[str, Dict[str, Any]] = {}
        requests_meta = []

        for intervention in interventions:
            params = self._compile_params(plan, intervention)
            studies, request_meta = await self._fetch_all_pages(params, audit=audit)
            requests_meta.append(request_meta)
            for study in studies:
                nct_id = (
                    study.get("protocolSection", {})
                    .get("identificationModule", {})
                    .get("nctId")
                )
                if nct_id:
                    all_studies[nct_id] = study

        return list(all_studies.values()), {"requests": requests_meta}

    def _compile_params(self, plan: AnalysisPlan, intervention: Optional[str]) -> Dict[str, Any]:
        """Translate safe internal filters into official `/studies` query parameters."""
        filters = plan.filters
        params: Dict[str, Any] = {
            "format": "json",
            "pageSize": settings.page_size,
            "countTotal": "true",
            "fields": ",".join(FIELDS),
        }
        if filters.condition:
            params["query.cond"] = filters.condition
        if intervention:
            params["query.intr"] = intervention
        if filters.sponsor:
            params["query.spons"] = filters.sponsor
        if filters.country:
            params["query.locn"] = filters.country
        return params

    async def _fetch_all_pages(
        self, params: Dict[str, Any], audit: Optional[AuditRun] = None
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Follow page tokens up to the configured limit and report truncation metadata."""
        studies: List[Dict[str, Any]] = []
        page_token: Optional[str] = None
        total_count: Optional[int] = None
        pages = 0

        while pages < settings.max_pages:
            page_params = dict(params)
            if page_token:
                page_params["pageToken"] = page_token
            response = await self._get_with_retry("/studies", params=page_params, audit=audit)
            body = response.json()
            pages += 1
            studies.extend(body.get("studies", []))
            total_count = body.get("totalCount", total_count)
            page_token = body.get("nextPageToken")
            if not page_token:
                break

        truncated = page_token is not None
        return studies, {
            "query_params": {key: value for key, value in params.items() if key != "fields"},
            "fields": FIELDS,
            "pages": pages,
            "retrieved_count": len(studies),
            "total_count": total_count,
            "truncated": truncated,
        }

    async def _get_with_retry(
        self, path: str, params: Optional[Dict[str, Any]] = None,
        audit: Optional[AuditRun] = None,
    ) -> httpx.Response:
        """Execute a GET request with bounded retry and per-attempt audit logging."""
        for attempt in range(3):
            started = time.monotonic()
            try:
                response = await self.client.get(path, params=params)
                response.raise_for_status()
                if audit:
                    body = response.json()
                    studies = body.get("studies", []) if isinstance(body, dict) else []
                    if path == "/version":
                        summary = body
                    elif path.startswith("/studies/"):
                        summary = {
                            "study_count": 1,
                            "items": response_items([body]),
                            "modules": sorted(body.get("protocolSection", {}).keys()),
                        }
                    else:
                        summary = {
                            "study_count": len(studies),
                            "total_count": body.get("totalCount"),
                            "next_page_token_present": bool(body.get("nextPageToken")),
                            "items": response_items(studies),
                        }
                    audit.add_api_call(
                        method="GET", path=path, url=str(response.request.url),
                        params=dict(params or {}), status_code=response.status_code,
                        duration_ms=round((time.monotonic() - started) * 1000),
                        response=summary,
                        attempt=attempt + 1,
                        request_headers=dict(response.request.headers),
                    )
                return response
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                if audit:
                    status_code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                    audit.add_api_call(
                        method="GET", path=path,
                        url=str(getattr(getattr(exc, "request", None), "url", path)),
                        params=dict(params or {}), status_code=status_code,
                        duration_ms=round((time.monotonic() - started) * 1000),
                        error=f"{type(exc).__name__}: {exc}",
                        attempt=attempt + 1,
                        request_headers=dict(getattr(getattr(exc, "request", None), "headers", {})),
                    )
                retryable = not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in {
                    429, 502, 503, 504
                }
                if not retryable or attempt == 2:
                    raise
                await asyncio.sleep(0.25 * (2 ** attempt))
        raise RuntimeError("unreachable")
