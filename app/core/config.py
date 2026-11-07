"""Runtime settings. Values come from the environment (or .env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
DEV_DB_URL_FILE = ROOT / ".pgdata" / "database_url.txt"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    anthropic_api_key: str = ""
    database_url: str = ""
    model_fast: str = "claude-haiku-5-5"
    model_smart: str = "claude-sonnet-5-5"
    api_base_url: str = "http://localhost:8000"
    pack: str = "meridian_ap"

    data_dir: Path = ROOT / "data"
    packs_dir: Path = ROOT / "packs"
    log_dir: Path = ROOT / "logs"
    cache_dir: Path = ROOT / ".cache" / "llm"

    @property
    def pack_dir(self) -> Path:
        return self.packs_dir / self.pack

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
