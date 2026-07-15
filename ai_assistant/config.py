from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(REPO_ROOT / ".env")


def _split(value: str) -> list[str]:
    return [p.strip() for p in value.split(",") if p.strip()]


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    llm_model: str
    embed_model: str
    rag_include: list[str]
    index_path: Path

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            llm_model=os.getenv("LLM_MODEL", "gpt-5.5"),
            embed_model=os.getenv("EMBED_MODEL", "text-embedding-3-large"),
            rag_include=_split(
                os.getenv(
                    "RAG_INCLUDE",
                    "README.md,DOCKER.md,AGENTS.md,docs/**/*.md,docs/**/*.rst,"
                    "localstack-core/localstack/openapi.yaml,ai_assistant/support/data/faq.md",
                )
            ),
            index_path=REPO_ROOT / os.getenv("INDEX_PATH", "ai_assistant/.index.db"),
        )
