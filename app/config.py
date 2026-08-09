import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    """Immutable runtime settings loaded once from environment variables."""
    clinical_trials_base_url: str = os.getenv(
        "CLINICAL_TRIALS_BASE_URL", "https://clinicaltrials.gov/api/v2"
    )
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    visualization_model: str = os.getenv(
        "OPENAI_VISUALIZATION_MODEL", os.getenv("OPENAI_MODEL", "gpt-5-mini")
    )
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    request_timeout_seconds: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
    max_pages: int = int(os.getenv("MAX_PAGES", "20"))
    page_size: int = min(int(os.getenv("PAGE_SIZE", "1000")), 1000)
    citation_limit: int = int(os.getenv("CITATION_LIMIT", "20"))
    detail_fetch_limit: int = int(os.getenv("DETAIL_FETCH_LIMIT", "50"))
    detail_fetch_concurrency: int = int(os.getenv("DETAIL_FETCH_CONCURRENCY", "5"))
    audit_log_dir: str = os.getenv("AUDIT_LOG_DIR", "logs/agent_runs")


settings = Settings()
"""Environment-backed application configuration."""
