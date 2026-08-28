"""Type definitions for usage metrics.

These dataclasses are the schema between the chat instrumentation
hooks and the storage backend. They are *records*, not API
responses — the API converts them to JSON dicts with stable keys
for the dashboard.

Records are intentionally minimal: the dashboard aggregates
thousands of them per query, so each record carries only the fields
the aggregations need. Empty / unset fields are dropped before
serialisation to keep the on-disk JSONL compact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Storage records (written by the chat handler, read by the dashboard) ──


@dataclass
class LLMCallRecord:
    """One finished LLM chat call.

    Captured at the end of every streamed response, including
    cancelled ones — the partial token counts at cancel time are
    still useful for the dashboard (it counts the call, just with
    ``cancelled=True`` and a possibly low completion_tokens).
    """

    ts: str  # ISO-8601 UTC
    session_id: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    duration_ms: float
    status: str  # "ok" | "error" | "cancelled"
    user_id: str = ""  # IDaaS uid; "" = anonymous / legacy
    error: str = ""
    cancelled: bool = False


@dataclass
class ToolCallRecord:
    """One finished tool / MCP / skill invocation.

    ``kind`` discriminates the source:

    * ``"tool"`` — local / script tool executed by the chat handler.
    * ``"mcp"`` — an MCP server was attached to this chat (per
      attachment, not per individual MCP-tool call — that's the
      granularity the user-facing "MCP使用排名" wants: which MCPs do
      users reach for most often).
    * ``"skill"`` — a skill was attached to this chat (per
      attachment — same reasoning: which skills do users attach
      most often).
    """

    ts: str
    session_id: str
    kind: str  # "tool" | "mcp" | "skill"
    name: str  # tool model_name / mcp server slug / skill slug
    user_id: str = ""  # IDaaS uid; "" = anonymous / legacy
    duration_ms: float = 0.0
    status: str = "ok"  # "ok" | "error" | "cancelled"
    error: str = ""


# ── API response shapes ──────────────────────────────────────────────────────


@dataclass
class SummaryBucket:
    """Aggregated usage for a date range (or today)."""

    llm_call_count: int = 0
    llm_error_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    avg_duration_ms: float = 0.0
    error_rate: float = 0.0
    avg_tokens_per_call: float = 0.0
    tool_call_count: int = 0
    tool_error_count: int = 0
    skill_call_count: int = 0
    mcp_call_count: int = 0
    conversation_count: int = 0
    model_perf: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "llm_call_count": self.llm_call_count,
            "llm_error_count": self.llm_error_count,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "avg_duration_ms": round(self.avg_duration_ms, 2),
            "error_rate": round(self.error_rate, 4),
            "avg_tokens_per_call": round(self.avg_tokens_per_call, 2),
            "tool_call_count": self.tool_call_count,
            "tool_error_count": self.tool_error_count,
            "skill_call_count": self.skill_call_count,
            "mcp_call_count": self.mcp_call_count,
            "conversation_count": self.conversation_count,
            "model_perf": self.model_perf,
        }


@dataclass
class RankedItem:
    """One ranked entity with usage + quality stats.

    Fields unused for a given kind stay at their default zero —
    e.g. tool ranking has ``avg_tokens=0`` (we don't track per-tool
    token cost), model ranking has ``error_count=0`` (LLM errors
    are surfaced through the LLM summary, not the model ranking).
    """

    key: str
    count: int = 0
    error_count: int = 0
    error_rate: float = 0.0
    avg_duration_ms: float = 0.0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    avg_tokens: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.key,
            "count": self.count,
            "error_count": self.error_count,
            "error_rate": round(self.error_rate, 4),
            "avg_duration_ms": round(self.avg_duration_ms, 2),
            "p50_ms": round(self.p50_ms, 2),
            "p95_ms": round(self.p95_ms, 2),
            "p99_ms": round(self.p99_ms, 2),
            "avg_tokens": round(self.avg_tokens, 2),
        }


@dataclass
class RankingPage:
    items: list[RankedItem]
    total: int


@dataclass
class TrendPoint:
    """One day of aggregated usage. Empty days are zero-filled."""

    date: str
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    tool_calls: int = 0
    skill_calls: int = 0
    mcp_calls: int = 0
    conversations: int = 0
    avg_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "llm_calls": self.llm_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "tool_calls": self.tool_calls,
            "skill_calls": self.skill_calls,
            "mcp_calls": self.mcp_calls,
            "conversations": self.conversations,
            "avg_duration_ms": round(self.avg_duration_ms, 2),
        }


__all__ = [
    "LLMCallRecord",
    "ToolCallRecord",
    "RankedItem",
    "RankingPage",
    "SummaryBucket",
    "TrendPoint",
]
