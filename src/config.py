"""Application Configuration (Requirement D4: 12-factor runtime configuration)."""

import os
from typing import Optional


def _load_dotenv(path: str) -> None:
    """Minimal stdlib .env loader. Real environment variables always take precedence."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))


class Settings:
    def __init__(self):
        # Service configuration
        self.APP_ENV: str = os.getenv("APP_ENV", "development")
        self.SERVICE_NAME: str = os.getenv("SERVICE_NAME", "securities-grievance-routing")
        self.PORT: int = int(os.getenv("PORT", "8000"))
        self.HOST: str = os.getenv("HOST", "0.0.0.0")
        self.LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

        # SLO Targets (Requirement D6)
        # Declared beforehand: p95 SLO for complete run < 4.0 seconds (on stub/fast model)
        self.SLO_P95_SECONDS: float = float(os.getenv("SLO_P95_SECONDS", "4.0"))
        self.SLO_P50_SECONDS: float = float(os.getenv("SLO_P50_SECONDS", "1.5"))

        # LLM Provider Configuration
        # Providers: "stub" (for reproducible benchmarks, load tests, offline demos), "gemini", "openai"
        self.LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "stub")
        self.LLM_API_KEY: Optional[str] = os.getenv("LLM_API_KEY", None)
        self.LLM_MODEL: str = os.getenv("LLM_MODEL", "stub-evaluator-v2")
        self.LLM_TIMEOUT_SECONDS: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "10.0"))
        self.LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "3"))
        # Optional: OpenAI-compatible endpoint (Groq, OpenRouter, local Ollama at http://localhost:11434/v1)
        self.LLM_BASE_URL: Optional[str] = os.getenv("LLM_BASE_URL") or None
        # Client-side cap on LLM requests per minute (0 = unlimited). Free API tiers allow ~10-15 RPM.
        self.LLM_MAX_RPM: float = float(os.getenv("LLM_MAX_RPM", "0"))
        # Per-1M-token prices used by the cost ledger (Requirement L5); set them to your model's list price
        self.LLM_COST_PER_1M_INPUT: float = float(os.getenv("LLM_COST_PER_1M_INPUT", "0.15"))
        self.LLM_COST_PER_1M_OUTPUT: float = float(os.getenv("LLM_COST_PER_1M_OUTPUT", "0.60"))

        # Agent Loop Limits (Requirement A1)
        self.MAX_AGENT_STEPS: int = int(os.getenv("MAX_AGENT_STEPS", "6"))
        self.MAX_TOOL_CALLS: int = int(os.getenv("MAX_TOOL_CALLS", "8"))
        self.AGENT_TIMEOUT_SECONDS: float = float(os.getenv("AGENT_TIMEOUT_SECONDS", "25.0"))

        # Retrieval & Corpus
        self.CORPUS_DIR: str = os.getenv(
            "CORPUS_DIR",
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "corpus"),
        )
        self.INDEX_DIR: str = os.getenv(
            "INDEX_DIR",
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "index"),
        )
        self.CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "500"))
        self.CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "50"))
        self.RETRIEVAL_TOP_K: int = int(os.getenv("RETRIEVAL_TOP_K", "4"))

        # Rate Limiting & Caching (Requirement D7)
        self.RATE_LIMIT_RPS: float = float(os.getenv("RATE_LIMIT_RPS", "15.0"))
        self.RATE_LIMIT_BURST: int = int(os.getenv("RATE_LIMIT_BURST", "30"))
        self.CACHE_ENABLED: bool = os.getenv("CACHE_ENABLED", "true").lower() == "true"
        self.CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "3600"))

        # Circuit Breaker (Requirement A5)
        self.CIRCUIT_BREAKER_FAILURE_THRESHOLD: int = int(os.getenv("CIRCUIT_BREAKER_FAILURE_THRESHOLD", "4"))
        self.CIRCUIT_BREAKER_RECOVERY_TIMEOUT_SECONDS: float = float(os.getenv("CIRCUIT_BREAKER_RECOVERY_TIMEOUT_SECONDS", "15.0"))

        # Observability & Tracing (Requirement D5)
        self.PROMETHEUS_METRICS_ENABLED: bool = os.getenv("PROMETHEUS_METRICS_ENABLED", "true").lower() == "true"
        self.OPENTELEMETRY_EXPORTER_ENDPOINT: str = os.getenv("OPENTELEMETRY_EXPORTER_ENDPOINT", "http://localhost:4317")
        self.OTEL_TRACING_ENABLED: bool = os.getenv("OTEL_TRACING_ENABLED", "false").lower() == "true"

        # Redis Queue
        self.REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.USE_EMBEDDED_QUEUE: bool = os.getenv("USE_EMBEDDED_QUEUE", "true").lower() == "true"

        # Active Prompt Version (Requirement L2)
        self.ACTIVE_PROMPT_VERSION: str = os.getenv("ACTIVE_PROMPT_VERSION", "v2.0")


settings = Settings()
