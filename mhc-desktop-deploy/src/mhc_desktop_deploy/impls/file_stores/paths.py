"""Filesystem paths for mhc-desktop-backend local state.

All persistent state lives under ``~/.mhc-desktop/``. The provider
config file (``providers.json``) uses the **same JSON schema** as
mh-local's ``~/.config/mh-local/providers.json`` so users can copy
between the two.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("mhc_desktop_backend")

DATA_DIR = Path.home() / ".mhc-desktop"
LOGS_DIR = DATA_DIR / "logs"
PROVIDERS_FILE = DATA_DIR / "providers.json"
SESSIONS_DIR = DATA_DIR / "sessions"
SESSIONS_INDEX = SESSIONS_DIR / "index.json"
SKILLS_DIR = DATA_DIR / "skills"
SKILLS_STATE_FILE = (
    DATA_DIR / "skills-state.json"
)  # enabled flags + meta outside the skill folder
MCP_DIR = DATA_DIR / "mcp"
MCP_STATE_FILE = DATA_DIR / "mcp-state.json"
TOOLS_DIR = DATA_DIR / "tools"
TOOLS_STATE_FILE = DATA_DIR / "tools-state.json"
PREFS_FILE = DATA_DIR / "prefs.json"
METRICS_FILE = DATA_DIR / "metrics.jsonl"

_TEMPLATE_PROVIDERS = json.dumps(
    [
        {
            "name": "my-provider",
            "provider_type": "openai",
            "api_key": "",
            "base_url": "",
            "default_model": "",
            "description": "Configure your LLM provider here",
            "models": [],
        }
    ],
    indent=2,
    ensure_ascii=False,
)


def ensure_dirs() -> None:
    """Create the directory tree and seed an empty provider template.

    The template is only written when ``providers.json`` is missing or
    empty, so user edits are preserved across restarts.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    MCP_DIR.mkdir(parents=True, exist_ok=True)
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    if not PROVIDERS_FILE.exists():
        PROVIDERS_FILE.write_text(_TEMPLATE_PROVIDERS, encoding="utf-8")
        logger.info("Created %s", PROVIDERS_FILE)
    elif PROVIDERS_FILE.stat().st_size == 0:
        logger.warning("%s is empty — restoring template", PROVIDERS_FILE)
        PROVIDERS_FILE.write_text(_TEMPLATE_PROVIDERS, encoding="utf-8")
