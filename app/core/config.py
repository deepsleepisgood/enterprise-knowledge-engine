"""Runtime settings. Values come from the environment (or .env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
DEV_DB_URL_FILE = ROOT / ".pgdata" / "database_url.txt"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    llm_provider: str = "anthropic"  # anthropic | nim
    anthropic_api_key: str = ""
    nvidia_api_key: str = ""
    nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    nim_timeout_s: float = 300
    nim_max_rpm: int = 35  # NIM free tier allows ~40 requests/minute; keep headroom
    nim_max_concurrent: int = 4  # parallel bursts get 429s well below the per-minute limit
    database_url: str = ""
    model_fast: str = "claude-haiku-5-5"
    model_smart: str = "claude-sonnet-5-5"
    model_vision: str = ""  # empty: use model_smart
    api_base_url: str = "http://localhost:8000"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"  # comma-separated
    cors_origin_regex: str = r"https://[\w-]+\.vercel\.app"  # the deployed web app
    max_upload_mb: int = 50
    tenant_id: str = "default"
    schema_mode: str = "induced"  # induced | baseline (a plug-in's hand-written schema)
    plugins: str = "ap"  # comma-separated plug-in folders under plugins_dir to enable
    worker_threads: int = 4
    # Owner approval of inputs that arrive after setup (BUILD_PLAN Phase 9). Bulk seeding and
    # evaluation scripts turn it off for their own runs.
    governance: bool = True
    # Watched folder (SCOPE 4.1): polled by the worker; empty WATCH_DIR means data/inbox.
    watch_enabled: bool = True
    watch_dir: str = ""
    watch_interval_s: int = 30

    # Answer pipeline (BUILD_PLAN Phase 4)
    rerank_model: str = "BAAI/bge-reranker-base"  # fastembed cross-encoder; "none" disables
    retrieve_k: int = 20  # full-text and vector candidates each
    answer_passages: int = 6  # kept after reranking
    graph_facts: int = 10  # graph-context facts, ranked by similarity
    abstain_rerank_score: float = -4.0  # top reranker logit below this: unsupported
    abstain_vector_score: float = 0.55  # used when the reranker is off
    router_min_confidence: float = 0.6  # below this a calculator route falls back to lookup
    router_model: str = "fast"  # fast | smart | a model id
    early_calculator_inputs: bool = True  # read calculator inputs while routing (faster)
    early_retrieval: bool = True  # search while the router runs (no scope/date asked)
    answer_thinking: bool = False  # let reasoning models think on the answer path (slower)

    data_dir: Path = ROOT / "data"
    blob_dir: Path = ROOT / "data" / "blobs"
    plugins_dir: Path = ROOT / "plugins"
    log_dir: Path = ROOT / "logs"
    cache_dir: Path = ROOT / ".cache" / "llm"

    @property
    def llm_configured(self) -> bool:
        """True when the selected provider has a key."""
        if self.llm_provider == "nim":
            return bool(self.nvidia_api_key)
        return bool(self.anthropic_api_key)

    @property
    def enabled_plugins(self) -> list[str]:
        return [p.strip() for p in self.plugins.split(",") if p.strip()]

    def resolved_database_url(self) -> str:
        """DATABASE_URL, or the URL written by `scripts/dev_db.py start`."""
        if self.database_url:
            return self.database_url
        if DEV_DB_URL_FILE.exists():
            return DEV_DB_URL_FILE.read_text(encoding="utf-8").strip()
        raise RuntimeError(
            "DATABASE_URL is not set. Run `docker compose up -d db` and set it, "
            "or run `python scripts/dev_db.py start`."
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
