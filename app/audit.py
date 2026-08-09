import json
import shlex
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


_WRITE_LOCK = threading.Lock()


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp for consistent log ordering."""
    return datetime.now(timezone.utc).isoformat()


class AuditRun:
    """Collect one agent run and append it as a single JSONL record."""

    def __init__(self, user_request: Dict[str, Any], log_dir: str = "logs/agent_runs") -> None:
        """Initialize an in-memory record that is written once on completion or failure."""
        self.request_id = str(uuid.uuid4())
        self.log_dir = Path(log_dir)
        self.record: Dict[str, Any] = {
            "request_id": self.request_id,
            "started_at": utc_now(),
            "completed_at": None,
            "status": "running",
            "user_request": user_request,
            "analysis_plan": None,
            "api_calls": [],
            "pipeline_events": [],
            "result_summary": None,
            "response_output": None,
            "error": None,
        }

    def set_plan(self, plan: Dict[str, Any]) -> None:
        """Record the validated plan actually used by the pipeline."""
        self.record["analysis_plan"] = plan

    def add_api_call(
        self,
        *,
        method: str,
        path: str,
        url: str,
        params: Optional[Dict[str, Any]],
        status_code: Optional[int],
        duration_ms: int,
        response: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        attempt: int = 1,
        request_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        """Record one external call with replay details and a bounded response summary."""
        safe_headers = {
            key: value for key, value in (request_headers or {}).items()
            if key.lower() in {"accept", "content-type", "user-agent"}
        }
        prepared_url = url
        self.record["api_calls"].append({
            "sequence": len(self.record["api_calls"]) + 1,
            "timestamp": utc_now(),
            "method": method,
            "path": path,
            "attempt": attempt,
            "request": {
                "url": prepared_url,
                "query_string": prepared_url.split("?", 1)[1] if "?" in prepared_url else "",
                "params": params or {},
                "param_list": [
                    {"name": str(key), "value": value} for key, value in (params or {}).items()
                ],
                "headers": safe_headers,
                "replay_curl": f"curl -fsS {shlex.quote(prepared_url)}",
            },
            # Kept for backward compatibility with earlier monitoring records.
            "url": prepared_url,
            "params": params or {},
            "status_code": status_code,
            "duration_ms": duration_ms,
            "response": response,
            "error": error,
        })

    def add_pipeline_event(self, action: str, **details: Any) -> None:
        """Append an ordered, user-visible pipeline event."""
        self.record["pipeline_events"].append({
            "sequence": len(self.record["pipeline_events"]) + 1,
            "timestamp": utc_now(),
            "action": action,
            **details,
        })

    def set_response_output(self, response: Dict[str, Any]) -> None:
        """Store the renderable response so monitoring can replay it in User App."""
        self.record["response_output"] = response

    def complete(self, result_summary: Dict[str, Any]) -> None:
        """Mark the run successful and write its final JSONL record once."""
        self.record["status"] = "success"
        self.record["result_summary"] = result_summary
        self.record["completed_at"] = utc_now()
        self._write()

    def fail(self, exc: Exception) -> None:
        """Mark the run failed and persist the exception type and message."""
        self.record["status"] = "error"
        self.record["error"] = {"type": type(exc).__name__, "message": str(exc)}
        self.record["completed_at"] = utc_now()
        self._write()

    def _write(self) -> None:
        """Append the complete run atomically to its date-partitioned JSONL file."""
        date = self.record["started_at"][:10]
        path = self.log_dir / f"{date}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(self.record, ensure_ascii=False, separators=(",", ":"))
        with _WRITE_LOCK:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")


def response_items(studies: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep monitoring useful without duplicating full ClinicalTrials.gov payloads."""
    items = []
    for study in studies:
        identification = study.get("protocolSection", {}).get("identificationModule", {})
        items.append({
            "nct_id": identification.get("nctId"),
            "title": identification.get("briefTitle"),
        })
    return items
"""Append-only, privacy-aware audit logging for agent executions."""
