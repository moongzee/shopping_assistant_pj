from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


def _load_dotenv() -> None:
    """Load dotenv files (without overriding existing env)."""
    try:
        from dotenv import load_dotenv
    except Exception:
        return

    here = Path(__file__).resolve()
    # Repo root = .../shopping_assistant
    repo_root = here.parents[2]

    candidates = [
        repo_root / "agent" / ".env",
        repo_root / ".env",
    ]

    loaded: List[str] = []
    for p in candidates:
        if p.exists() and p.is_file():
            load_dotenv(dotenv_path=p, override=False)
            loaded.append(str(p))

    global LOADED_DOTENV_FILES
    LOADED_DOTENV_FILES = loaded


LOADED_DOTENV_FILES: List[str] = []
_load_dotenv()


def _env(name: str, default: str | None = "") -> str:
    """
    Read env var. If unset/empty, return `default`.

    - `default` can be omitted (defaults to empty string) so callers can mark
      values as "optional" without repeating `""` everywhere.
    """
    v = os.getenv(name)
    if v is None or v == "":
        # If default is explicitly None, treat as empty string to keep import-time safe.
        return "" if default is None else default
    return v


def _env_list(name: str, default: List[str]) -> List[str]:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    return [x.strip() for x in v.split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    # MCP
    mcp_snowflake_url: str = _env(
        "MCP_SNOWFLAKE_URL"
    )
    mcp_cortex_search_tool: str = _env("MCP_CORTEX_SEARCH_TOOL")
    mcp_cortex_search_service_name: str = _env("MCP_CORTEX_SEARCH_SERVICE_NAME")
    mcp_cortex_search_database_name: str = _env("MCP_CORTEX_SEARCH_DATABASE_NAME")
    mcp_cortex_search_schema_name: str = _env("MCP_CORTEX_SCHEMA_NAME")

    mcp_cortex_analyst_url: str = _env(
        "MCP_CORTEX_ANALYST_URL"
    )
    mcp_cortex_analyst_tool: str = _env("MCP_CORTEX_ANALYST_TOOL")
    mcp_cortex_analyst_query_param: str = _env("MCP_CORTEX_ANALYST_QUERY_PARAM", "query")

    # DSPy / LLM
    dspy_model: str = _env("DSPY_MODEL")

    # API
    memory_max_turns: int = int(_env("MEMORY_MAX_TURNS", "6"))
    stream_chunk_chars: int = int(_env("STREAM_CHUNK_CHARS", "24"))
    stream_delay_ms: int = int(_env("STREAM_DELAY_MS", "15"))
    frontend_origins: List[str] = field(
        default_factory=lambda: _env_list(
            "FRONTEND_ORIGINS", ["http://localhost:3000", "http://127.0.0.1:3000"]
        )
    )

    # DSPy artifacts
    dspy_artifacts_dir: str = _env("DSPY_ARTIFACTS_DIR", "agent/artifacts")
    artifact_relaxed_constraints: str = _env(
        "DSPY_ARTIFACT_RELAXED_CONSTRAINTS", "relaxed_constraints.json"
    )
    artifact_product_ranker: str = _env("DSPY_ARTIFACT_PRODUCT_RANKER", "product_ranker.json")
    artifact_fusion_decision: str = _env("DSPY_ARTIFACT_FUSION_DECISION", "fusion_decision.json")

    # Admin
    admin_api_key: str = _env("ADMIN_API_KEY", "")


SETTINGS = Settings()

