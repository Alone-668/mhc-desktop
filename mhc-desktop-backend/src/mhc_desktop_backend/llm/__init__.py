"""LLM-related helpers — provider factory and built-in presets."""

from mhc_desktop_backend.llm.factory import build_provider
from mhc_desktop_backend.llm.presets import PRESETS, get_preset

__all__ = ["build_provider", "PRESETS", "get_preset"]
