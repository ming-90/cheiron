import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings


def list_runs(limit: int = 50, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Return newest run summaries, optionally filtered by final status."""
    runs: List[Dict[str, Any]] = []
    log_dir = Path(settings.audit_log_dir)
    if not log_dir.exists():
        return runs

    for path in sorted(log_dir.glob("*.jsonl"), reverse=True):
        lines = path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if status and record.get("status") != status:
                continue
            runs.append(_summary(record))
            if len(runs) >= limit:
                return runs
    return runs


def get_run(request_id: str) -> Optional[Dict[str, Any]]:
    """Find one complete audit record by request ID."""
    log_dir = Path(settings.audit_log_dir)
    if not log_dir.exists():
        return None
    for path in sorted(log_dir.glob("*.jsonl"), reverse=True):
        for line in path.read_text(encoding="utf-8").splitlines():
            if request_id not in line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("request_id") == request_id:
                return record
    return None


def dashboard_stats(runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate top-level monitoring metrics for the supplied run summaries."""
    total = len(runs)
    successes = sum(run["status"] == "success" for run in runs)
    api_calls = sum(run["api_call_count"] for run in runs)
    durations = [run["duration_ms"] for run in runs if run["duration_ms"] is not None]
    return {
        "total_runs": total,
        "success_rate": round(successes / total * 100, 1) if total else 0,
        "api_calls": api_calls,
        "average_duration_ms": round(sum(durations) / len(durations)) if durations else 0,
    }


def _summary(record: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce a full audit record to the fields needed by the runs table."""
    api_calls = record.get("api_calls", [])
    studies_call = next((call for call in api_calls if call.get("path") == "/studies"), None)
    request_details = (studies_call or {}).get("request", {})
    duration_ms = sum(call.get("duration_ms") or 0 for call in api_calls)
    request = record.get("user_request", {})
    result = record.get("result_summary") or {}
    return {
        "request_id": record.get("request_id"),
        "started_at": record.get("started_at"),
        "completed_at": record.get("completed_at"),
        "status": record.get("status"),
        "query": request.get("query", ""),
        "api_call_count": len(api_calls),
        "duration_ms": duration_ms,
        "records_retrieved": result.get("records_retrieved", 0),
        "records_used": result.get("records_used", 0),
        "visualization_count": len(result.get("visualizations", [])),
        "request_params": request_details.get("params", (studies_call or {}).get("params", {})),
        "request_url": request_details.get("url", (studies_call or {}).get("url")),
        "error": record.get("error"),
    }
"""Read JSONL audit records and shape them for the monitoring frontend."""
