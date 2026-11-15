"""Runtime settings. Values come from the environment (or .env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
DEV_DB_URL_FILE = ROOT / ".pgdata" / "database_url.txt"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    llm_provider: str = "anthropic"  # anthropic | nim | openai
    anthropic_api_key: str = ""
    # Anthropic calls at once for the whole process (more wait), and how often the SDK retries a
    # rate limit or overload (it honours Retry-After). The SDK's own default gives up after 2.
    anthropic_max_concurrent: int = 8
    anthropic_max_retries: int = 6
    anthropic_timeout_s: float = 120
    nvidia_api_key: str = ""
    # Any OpenAI-compatible endpoint runs through the NIM transport: set NIM_BASE_URL to it.
    # Isoquant (api.isoquant.ai) uses ISOQUANT_API_KEY; everything else uses NVIDIA_API_KEY.
    isoquant_api_key: str = ""
    nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    nim_timeout_s: float = 300
    nim_max_rpm: int = 35  # NIM free tier allows ~40 requests/minute; keep headroom
    nim_max_concurrent: int = 4  # parallel bursts get 429s well below the per-minute limit
    # OpenAI (LLM_PROVIDER=openai) uses the same OpenAI-compatible transport as NIM.
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_max_rpm: int = 500  # paid tiers allow far more than NIM's free tier
    openai_max_concurrent: int = 8
    # Reasoning models (o-series, gpt-5*) take no temperature; this effort is sent when a call
    # asks for thinking off. "low" is accepted by every reasoning model.
    openai_reasoning_effort_off: str = "minimal"  # falls back to "low" if a model refuses it
    openai_timeout_s: float = 120  # a stuck call fails fast instead of holding a transaction
    # Reasoning models spend part of max_completion_tokens on hidden thinking, so a budget sized
    # for the visible answer runs out. Their budget is raised to at least this. It is a cap,
    # not a charge: only tokens actually generated are billed.
    openai_reasoning_min_tokens: int = 16384
    # Prices for models missing from llm.PRICES_PER_MTOK, USD per million tokens:
    # "model=input/output,model2=input/output". Unknown models are logged with cost null.
    model_prices: str = ""
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
    # Database connections per process. Each answer keeps one open for its whole snapshot (about
    # 10-20 s, model calls included) and opens a second for the parallel search, so the pool must
    # cover about two per answer being worked on. SQLAlchemy's own default (5 + 10) queued the
    # 16th connection. Use Neon's pooled (-pooler) URL when these add up past the direct limit.
    db_pool_size: int = 10
    db_max_overflow: int = 30
    db_pool_timeout_s: float = 60
    # Answers worked on at once through POST /ask/jobs; more wait their turn in memory.
    ask_concurrency: int = 16
    # Owner approval of inputs that arrive after setup (BUILD_PLAN Phase 9). Bulk seeding and
    # evaluation scripts turn it off for their own runs.
    governance: bool = True
    # Replay (Sources page): a separate tenant rebuilt from empty by feeding the plug-ins'
    # `replay` file lists in order. The owner is seeding it, so governance is off there only.
    replay_tenant: str = "replay"
    # Watched folder (SCOPE 4.1): polled by the worker; empty WATCH_DIR means data/inbox.
    watch_enabled: bool = True
    watch_dir: str = ""
    watch_interval_s: int = 30

    # Digest delivery (Phase 11). Each channel works once its settings are filled in; empty means
    # the app offers "Copy as text" only. Email: any SMTP server (Microsoft 365, Gmail, SendGrid…).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_security: str = "starttls"  # starttls | ssl | none
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""  # empty: smtp_user
    digest_email_to: str = ""  # comma-separated recipients (a team list works best)
    # Teams: the URL of a "When a Teams webhook request is received" workflow (Workflows app).
    teams_webhook_url: str = ""
    digest_send_at: str = ""  # "HH:MM" local time for an automatic daily send; empty: manual only
    digest_utc_offset_minutes: int = 0  # the team's time zone, minutes east of UTC
    digest_skip_empty: bool = True  # no automatic send on a day without changes
    web_base_url: str = ""  # link back to the app in sent digests (e.g. https://app.example.com)

    # Answer pipeline (BUILD_PLAN Phase 4)
    rerank_model: str = "BAAI/bge-reranker-base"  # fastembed cross-encoder; "none" disables
    # CPU threads for the local embedding and reranker models; 0 = the runtime's default (one
    # per CPU it sees). In a container that is the host's CPU count, not the share the service
    # gets, so set it to the service's vCPUs there (GET /health shows what the process sees).
    model_threads: int = 0
    retrieve_k: int = 20  # full-text and vector candidates each
    # The reranker is the slowest local step (~0.5 s per passage on a few CPUs) and one runs at a
    # time, so under load every question queues behind it: score this many fused candidates,
    # reading this many characters of each (header included).
    # Dev split, 15 Nov (88 questions): 1200 chars kept the same top 6 for every question;
    # fewer candidates (16, 12) started dropping the gold source.
    rerank_k: int = 20
    rerank_chars: int = 1200
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
    # Model that grades evaluation answers; empty = MODEL_SMART. Fix it when comparing runs
    # that use different answer models, so the grading stays the same.
    judge_model: str = ""

    @field_validator("data_dir", "blob_dir", "log_dir", "cache_dir", mode="before")
    @classmethod
    def _empty_path_is_default(cls, v: object, info: object) -> object:
        """`BLOB_DIR=` (empty) in .env means "use the default", not the current folder."""
        if v is None or (isinstance(v, str) and not v.strip()):
            return cls.model_fields[info.field_name].default  # type: ignore[attr-defined]
        return v

    @property
    def llm_configured(self) -> bool:
        """True when the selected provider has a key."""
        if self.llm_provider in ("nim", "openai"):
            return bool(self.chat_api_key)
        return bool(self.anthropic_api_key)

    @property
    def is_openai(self) -> bool:
        return self.llm_provider.strip().lower() == "openai"

    @property
    def chat_base_url(self) -> str:
        """The OpenAI-compatible endpoint for the selected provider."""
        return self.openai_base_url if self.is_openai else self.nim_base_url

    @property
    def chat_timeout_s(self) -> float:
        return self.openai_timeout_s if self.is_openai else self.nim_timeout_s

    @property
    def chat_max_rpm(self) -> int:
        return self.openai_max_rpm if self.is_openai else self.nim_max_rpm

    @property
    def chat_max_concurrent(self) -> int:
        return self.openai_max_concurrent if self.is_openai else self.nim_max_concurrent

    @property
    def is_isoquant(self) -> bool:
        return not self.is_openai and "isoquant.ai" in self.nim_base_url

    @property
    def chat_api_key(self) -> str:
        """The key for chat_base_url."""
        if self.is_openai:
            return self.openai_api_key
        return self.isoquant_api_key if self.is_isoquant else self.nvidia_api_key

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
