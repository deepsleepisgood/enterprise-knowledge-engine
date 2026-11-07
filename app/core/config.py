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
    tenant_id: str = "default"
    schema_mode: str = "induced"  # induced | baseline (a plug-in's hand-written schema)
    plugins: str = "ap"  # comma-separated plug-in folders under plugins_dir to enable
    worker_threads: int = 4

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
