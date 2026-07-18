"""
Load .env from project root so API keys work when running from any directory.
"""

import os
from pathlib import Path

from dotenv import load_dotenv


def find_project_env() -> Path | None:
    """Find .env by walking up from cwd (so CLI/scripts work from any subdir)."""
    cwd = Path(os.getcwd()).resolve()
    for parent in [cwd, *cwd.parents]:
        env_file = parent / ".env"
        if env_file.is_file():
            return env_file
    return None


def load_env() -> None:
    """Load .env from project root; fall back to cwd. Does not override existing env."""
    env_path = find_project_env()
    if env_path:
        load_dotenv(env_path, override=False)
    else:
        load_dotenv()


def require_llm_key() -> bool:
    """
    Return True if a usable LLM provider key is set.

    Which key is actually required depends on AUTOHEDGE_MODEL (see
    autohedge/workers.py): OPENAI_API_KEY for the default "gpt-*"
    models, GEMINI_API_KEY for "gemini/*" models.
    """
    return bool(os.getenv("OPENAI_API_KEY") or os.getenv("GEMINI_API_KEY"))
