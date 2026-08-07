"""
Loads settings from your .env file into one place so every other file
can just do: from config import settings
"""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

# Disable ChromaDB telemetry globally before anything is imported
os.environ["ANONYMIZED_TELEMETRY"] = "False"

from dotenv import load_dotenv

load_dotenv(override=True)  # reads the ".env" file in this folder

# Mutagent directory paths (single source of truth for prompts, traces, reports)
PROMPTS_DIR = REPO_ROOT / "backend" / "mutagent" / "prompts"
TRACES_DIR  = REPO_ROOT / "backend" / "mutagent" / "traces"
REPORTS_DIR = REPO_ROOT / "backend" / "mutagent" / "reports"


class Settings:
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    GROQ_API_KEY: str   = os.getenv("GROQ_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GITHUB_TOKEN: str   = os.getenv("GITHUB_TOKEN", "")

    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "")
    OLLAMA_MODEL: str    = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

    CHROMA_PERSIST_DIR: str = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma")

    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "gemini-embedding-2")
    LLM_MODEL: str       = os.getenv("LLM_MODEL", "llama-3.1-8b-instant")

    TOP_K: int        = int(os.getenv("TOP_K", "25"))
    RERANK_TOP_K: int = int(os.getenv("RERANK_TOP_K", "5"))
    CHUNK_SIZE: int   = int(os.getenv("CHUNK_SIZE", "500"))
    CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "50"))

    HYDE_ENABLED: bool = os.getenv("HYDE_ENABLED", "true").lower() == "true"


settings = Settings()


def load_prompt(name: str) -> str:
    """Load a prompt template from backend/mutagent/prompts/<name>.txt.
    Single source of truth — prompts are never inlined in Python files.
    """
    path = PROMPTS_DIR / f"{name}.txt"
    return path.read_text(encoding="utf-8").strip()


def repo_id_from_url(repo_url: str) -> str:
    """Canonical repo_url -> repo_id derivation used by Chroma and graph store.
    Changing this invalidates every existing index and graph.
    """
    slug = repo_url.rstrip("/").split("github.com/")[-1].removesuffix(".git")
    return slug.replace("/", "__")
