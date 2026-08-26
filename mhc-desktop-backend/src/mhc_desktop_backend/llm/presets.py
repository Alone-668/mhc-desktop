"""Built-in provider presets.

These are templates the user can pick from when adding a new provider
through the UI. Each preset carries:

* ``provider_type`` — matched against :class:`minimal_harness.llm.factory`
    driver names (``openai`` and ``anthropic`` are built in; everything
    OpenAI-compatible reuses the OpenAI driver with a custom ``base_url``).
* ``base_url`` — vendor's API root.
* ``default_model`` — a sensible default; the user can override.
* ``models`` — list of well-known models with their max_context tokens.

``api_key`` is intentionally **empty** — the user pastes their own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    description: str
    provider_type: str
    base_url: str
    default_model: str
    models: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "provider_type": self.provider_type,
            "base_url": self.base_url,
            "default_model": self.default_model,
            "models": list(self.models),
        }


PRESETS: list[Preset] = [
    Preset(
        id="openai",
        label="OpenAI",
        description="OpenAI official API",
        provider_type="openai",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        models=[
            {"code": "gpt-4o", "display_name": "GPT-4o", "max_context": 128000},
            {
                "code": "gpt-4o-mini",
                "display_name": "GPT-4o mini",
                "max_context": 128000,
            },
            {"code": "gpt-4.1", "display_name": "GPT-4.1", "max_context": 1047576},
            {
                "code": "gpt-4.1-mini",
                "display_name": "GPT-4.1 mini",
                "max_context": 1047576,
            },
            {"code": "o3-mini", "display_name": "o3-mini", "max_context": 200000},
        ],
    ),
    Preset(
        id="anthropic",
        label="Anthropic Claude",
        description="Anthropic Claude API",
        provider_type="anthropic",
        base_url="https://api.anthropic.com",
        default_model="claude-3-5-sonnet-latest",
        models=[
            {
                "code": "claude-3-5-sonnet-latest",
                "display_name": "Claude 3.5 Sonnet",
                "max_context": 200000,
            },
            {
                "code": "claude-3-5-haiku-latest",
                "display_name": "Claude 3.5 Haiku",
                "max_context": 200000,
            },
            {
                "code": "claude-3-opus-latest",
                "display_name": "Claude 3 Opus",
                "max_context": 200000,
            },
        ],
    ),
    Preset(
        id="deepseek",
        label="DeepSeek",
        description="DeepSeek (OpenAI-compatible)",
        provider_type="openai",
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        models=[
            {
                "code": "deepseek-chat",
                "display_name": "DeepSeek-V3 Chat",
                "max_context": 64000,
            },
            {
                "code": "deepseek-reasoner",
                "display_name": "DeepSeek-R1 Reasoner",
                "max_context": 64000,
            },
        ],
    ),
    Preset(
        id="moonshot",
        label="Moonshot Kimi",
        description="Moonshot Kimi (OpenAI-compatible)",
        provider_type="openai",
        base_url="https://api.moonshot.cn/v1",
        default_model="moonshot-v1-8k",
        models=[
            {
                "code": "moonshot-v1-8k",
                "display_name": "Moonshot v1 8k",
                "max_context": 8000,
            },
            {
                "code": "moonshot-v1-32k",
                "display_name": "Moonshot v1 32k",
                "max_context": 32000,
            },
            {
                "code": "moonshot-v1-128k",
                "display_name": "Moonshot v1 128k",
                "max_context": 128000,
            },
        ],
    ),
    Preset(
        id="zhipu",
        label="Zhipu GLM",
        description="Zhipu GLM (OpenAI-compatible)",
        provider_type="openai",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        default_model="glm-4-flash",
        models=[
            {
                "code": "glm-4-flash",
                "display_name": "GLM-4 Flash",
                "max_context": 128000,
            },
            {"code": "glm-4-plus", "display_name": "GLM-4 Plus", "max_context": 128000},
            {"code": "glm-z1-air", "display_name": "GLM-Z1 Air", "max_context": 128000},
        ],
    ),
    Preset(
        id="ollama",
        label="Ollama (local)",
        description="Local Ollama server (OpenAI-compatible)",
        provider_type="openai",
        base_url="http://127.0.0.1:11434/v1",
        default_model="llama3.2",
        models=[
            {"code": "llama3.2", "display_name": "Llama 3.2", "max_context": 128000},
            {"code": "qwen2.5", "display_name": "Qwen 2.5", "max_context": 32000},
        ],
    ),
]


_PRESETS_BY_ID: dict[str, Preset] = {p.id: p for p in PRESETS}


def get_preset(preset_id: str) -> Preset | None:
    return _PRESETS_BY_ID.get(preset_id)
