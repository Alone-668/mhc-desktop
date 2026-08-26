"""SSE chat router.

POST ``/api/v1/chat`` accepts::

    {
      "provider": "openai",          # provider name from the store
      "model": "gpt-4o-mini",        # optional override
      "messages": [                  # plain dicts; v1 ignores images/files
        {"role": "user",   "content": "Hello"}
      ],
      "skills": ["commit-message"]   # optional, slug list — bodies are
                                     # sent as user-role attachments
    }

The system prompt is **assembled by the backend** (see
:func:`_build_system_prompt`) from a constant base + the user's
saved addition. The client does not pass it; this keeps the
"system must know X" facts (skill root, cwd, etc.) authoritative on
the server side so they cannot be lost when the user edits their
personal addition.

Streams Server-Sent Events:

* ``event: chunk\\ndata: {"content": "..."}\\n\\n``  — incremental text
* ``event: done\\ndata: {"usage": {...}}\\n\\n``       — final aggregate
* ``event: error\\ndata: {"message": "..."}\\n\\n``    — fatal failure

The ``StopAsyncIteration`` that signals end-of-stream is converted to a
``done`` event so clients don't have to special-case it.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from minimal_harness.llm.llm import StreamStalledError
from minimal_harness.memory import Message

from mhc_desktop_backend.llm import build_provider
from mhc_desktop_backend.mcp import (
    MCPError,
    collect_mcp_tools,
)
from mhc_desktop_backend.metrics.protocols import MetricsRepositoryProtocol
from mhc_desktop_backend.metrics.types import LLMCallRecord, ToolCallRecord
from mhc_desktop_backend.protocols import (
    ChatPolicy,
    PrefsStoreProtocol,
    ProviderStoreProtocol,
    SessionStoreProtocol,
    SkillStoreProtocol,
    StreamRegistryProtocol,
    ToolExecutor,
    ToolExecutorRegistryProtocol,
    ToolStoreProtocol,
)
from mhc_desktop_backend.skills import SkillError, format_skill_message
from mhc_desktop_backend.skills.models import Skill
from mhc_desktop_backend.stream_state import SessionStream
from mhc_desktop_backend.tools import (
    DEFAULT_TOOL_TIMEOUT_SECONDS,
    build_streaming_tool,
    build_tool_event_stream,
)

logger = logging.getLogger("mhc_desktop_backend")

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


def get_registry(request: Request) -> StreamRegistryProtocol:
    reg: StreamRegistryProtocol | None = getattr(
        request.app.state, "stream_registry", None
    )
    if reg is None:
        raise HTTPException(status_code=503, detail="stream registry not initialized")
    return reg


def get_session_store(request: Request):
    """Optional — sessions may be unavailable in older deployments."""
    return getattr(request.app.state, "session_store", None)


def get_store(request: Request) -> ProviderStoreProtocol:
    store: ProviderStoreProtocol | None = getattr(
        request.app.state, "provider_store", None
    )
    if store is None:
        raise HTTPException(status_code=503, detail="provider store not initialized")
    return store


def get_skill_store(request: Request) -> SkillStoreProtocol | None:
    """Optional — skills may be unavailable in older deployments."""
    return getattr(request.app.state, "skill_store", None)


def get_mcp_store(request: Request):
    """Optional — older deployments may not have MCP wired."""
    return getattr(request.app.state, "mcp_store", None)


def get_prefs_store(request: Request) -> PrefsStoreProtocol | None:
    """Optional — older deployments may not have prefs wired."""
    store: PrefsStoreProtocol | None = getattr(request.app.state, "prefs_store", None)
    return store


# ponytail: short, system-owned constant. Tuned for: skill file lookup.
# Add ONE thing at a time and re-measure. The skill path is rendered
# with ``~`` so the prompt doesn't leak the actual username on whatever
# machine this runs on — the user expands ``~`` mentally and the
# runtime tools always get absolute paths through the skill store.
def _format_skill_root() -> str:
    """Return ``~/...`` form of the skills directory for the system prompt.

    The runtime never sees this — it always uses the absolute path
    through the skill store. The textual form here is just so the
    model has a human-readable anchor; ``~`` keeps it portable.

    ``SKILLS_DIR`` moved to the deploy package; if deploy isn't
    installed we fall back to the legacy ``~/.mhc-desktop/skills``
    default so the kernel still renders a coherent prompt.
    """
    try:
        from mhc_desktop_deploy.impls.file_stores.paths import (
            SKILLS_DIR as _SKILLS_DIR,
        )
    except Exception:  # pragma: no cover — deploy absent
        _SKILLS_DIR = Path.home() / ".mhc-desktop" / "skills"
    home = Path.home()
    sk = _SKILLS_DIR.resolve()
    try:
        rel = sk.relative_to(home.resolve())
    except ValueError:
        # Home isn't a prefix (rare; e.g. custom data dir). Fall back
        # to the absolute path — better a long prompt than a broken one.
        return str(sk)
    return f"~/{rel.as_posix()}"


# Default system-prompt base. Lives in the kernel so dev / packaged
# installs ship a coherent base without any deploy wiring; deploys
# replace it via ``create_app(system_prompt_base=...)`` when they
# need a different brand/compliance boilerplate.
BASE_SYSTEM_PROMPT = (
    "Skills are folders on this machine.\n"
    "Their contents (scripts, references, assets) live under:\n"
    f"  {_format_skill_root()}/<slug>/\n"
)


def _resolve_system_prompt_base(override: str | None) -> str:
    """Pick the base string for the current request.

    Priority:

    1. ``override`` if it's a string — use verbatim.
    2. ``override`` if it's callable — invoke with no args, use
       the returned string. Deploys use this shape when the base
       depends on request state (per-tenant prefix, dynamic
       branding, etc.).
    3. Kernel default :data:`BASE_SYSTEM_PROMPT` otherwise.
    """
    if override is None:
        return BASE_SYSTEM_PROMPT
    if callable(override):
        try:
            return str(override())
        except Exception:  # pragma: no cover — defensive
            logger.exception("system_prompt_base callable raised; using default")
            return BASE_SYSTEM_PROMPT
    return str(override)


def _build_system_prompt(
    user_addition: str,
    *,
    base_override: str | None = None,
) -> str:
    """Assemble the full system prompt: chosen base + user addition.

    The base is required and always emitted. The addition is whatever
    the user saved in Settings; if missing/empty we skip the divider
    so the prompt doesn't end with a dangling "\\n\\n".

    ``base_override`` lets deploys swap the kernel default for their
    own brand / compliance boilerplate; ``None`` falls back to
    :data:`BASE_SYSTEM_PROMPT`.
    """
    base = _resolve_system_prompt_base(base_override).rstrip()
    addition = (user_addition or "").strip()
    if not addition:
        return base
    return f"{base}\n\n# User-specified system prompt\n\n{addition}"


def get_mcp_manager(request: Request):
    return getattr(request.app.state, "mcp_manager", None)


def get_tool_store(request: Request) -> ToolStoreProtocol | None:
    """Optional — older deployments may not have the Tools subsystem
    wired. We treat ``None`` as "no tools registered", not an error.
    """
    return getattr(request.app.state, "tool_store", None)


def get_metrics_repo(request: Request) -> MetricsRepositoryProtocol | None:
    """Optional — usage metrics may be disabled in tests or older
    deployments. ``None`` means "do not record"."""
    return getattr(request.app.state, "metrics_repo", None)


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _coerce_messages(payload: list[dict[str, Any]]) -> list[Message]:
    out: list[Message] = []
    for m in payload:
        role = m.get("role", "user")
        content = m.get("content", "")
        if isinstance(content, str):
            out.append({"role": role, "content": content})  # type: ignore[typeddict-item]
    return out


def _attach_user_metadata(coerced: list[Message], raw: list[dict[str, Any]]) -> None:
    """Carry per-message metadata from the wire payload into the
    coerced messages list. ``_coerce_messages`` keeps only
    role+content (matching the LLM contract); we want to remember
    the user's skills/mcp/tools attachment for persistence, and —
    crucially — the tool_calls on assistant messages plus the
    ``tool_call_id`` on role=tool messages so a previous turn that
    was cancelled mid-tool still carries its full context into
    the next LLM call."""
    for c, original in zip(coerced, raw):
        for key in (
            "skills",
            "mcp",
            "tools",
            "files",
            "tool_calls",
            "segments",
            "tool_call_id",
            "llm_tool_calls",
        ):
            if key in original and key not in c:
                c[key] = original[key]  # type: ignore[literal-required]


def _format_files_block(files: list[dict[str, Any]], user_text: str = "") -> str:
    r"""Render the [Attached files] block that we splice into a user
    message just before sending it to the LLM.

    Why this format
    ---------------

    The user often types a vague prompt like "what's in this?" or
    "summarize it" and expects the model to know they mean the
    attached file. The model's only signal that the attached file
    is the subject of the question is this block -- so the block
    has to: (a) make the linkage explicit, (b) lead with the
    absolute path so the tool-call schema (which prefers string
    fields near the top) picks it up reliably, and (c) never
    silently drop a file. An entry with no path still gets rendered
    as a name-only line so the model at least sees the attachment
    exists and can ask the user for the missing path.

    Format (one file):

        [Attached files -- 1 file. When the user asks about "this",
        "it", or refers to the attachment without naming it, they
        mean the file(s) listed below. Use the absolute path with
        your tools to read each file.]

          name: foo.txt
          path: C:\Users\demo\foo.txt
          size: 12 B

    Multi-file: numbered entries (file 1, file 2, ...).

    Determinism: the same input always produces byte-identical
    output, which is what the controller's prompt-cache key needs.
    """
    n = len(files)
    if n == 1:
        intro = (
            "[Attached files — 1 file. When the user asks about "
            '"this", "it", or refers to the attachment without '
            "naming it, they mean the file listed below. Use the "
            "absolute path with your tools to read it.]\n\n"
        )
    else:
        intro = (
            f"[Attached files — {n} files. When the user asks "
            'about "this", "these", "them", or refers to the '
            "attachments without naming them, they mean the files "
            "listed below. Use each absolute path with your tools "
            "to read the corresponding file.]\n\n"
        )
    lines: list[str] = []
    for idx, f in enumerate(files, start=1):
        name = str(f.get("name") or "").strip()
        path = str(f.get("path") or "").strip()
        size = f.get("size")
        if isinstance(size, bool):
            size_str = "? B"
        elif isinstance(size, (int, float)):
            size_str = f"{int(size)} B"
        else:
            size_str = "? B"
        # Name + path always render — never silently drop a file. A
        # missing path still produces a name-only line so the model
        # sees the attachment exists and can prompt for the path.
        if n > 1:
            lines.append(f"  file {idx}: {name or '(unnamed)'}")
            lines.append(
                f"    path: {path if path else '(no absolute path — ask the user for the file location)'}"
            )
            lines.append(f"    size: {size_str}")
        else:
            lines.append(f"  name: {name or '(unnamed)'}")
            lines.append(
                f"  path: {path if path else '(no absolute path — ask the user for the file location)'}"
            )
            lines.append(f"  size: {size_str}")
        lines.append("")  # blank line between entries
    body = "\n".join(lines).rstrip("\n")
    return intro + body


def _assemble_user_files(messages: list[Message]) -> list[Message]:
    """Return a deep-copied messages list with the ``files`` metadata
    on each user message spliced into its ``content`` as a plain-text
    block.

    Why this lives in the backend instead of the frontend:

    * The frontend ships only metadata (name / path / size) — never
      the binary — so the user message that lands on disk and gets
      reloaded after a session restart is clean. A session-reload
      reconstruction must NOT depend on us having re-inlined the
      paths at compose time, because we'd then have to do it twice
      (once on send, once on reload), which is exactly the duplication
      the task calls out as wrong.
    * The assembly is a one-shot, idempotent transformation of the
      wire-level metadata into the prompt the model actually sees.
      Doing it here, once per request, means the augmented content
      is reused unchanged across the controller's loop iterations
      (initial call + any tool-call follow-up), which is what
      provider-side prompt caching needs.
    * Original ``messages`` is untouched — the persistence path at
      the end of ``_event_stream`` writes the metadata-only version
      so a reload reproduces the same user message the user typed.
    """
    if not any(isinstance(m.get("files"), list) and m.get("files") for m in messages):
        return messages
    out: list[Message] = []
    for m in messages:
        files = m.get("files") if m.get("role") == "user" else None
        if not files:
            out.append(m)
            continue
        # Deep-copy the dict so the original is untouched even when
        # downstream code mutates an entry (it doesn't today, but the
        # contract is "do not mutate the caller's list").
        new_m = dict(m)
        content = m.get("content") or ""
        if not isinstance(content, str):
            content = ""
        block = _format_files_block(files)
        new_content = f"{content.rstrip()}\n\n{block}" if content.strip() else block
        new_m["content"] = new_content
        out.append(new_m)  # type: ignore[typeddict-item]
    return out


async def _resolve_skill_messages(
    slugs: list[str],
    skill_store: SkillStoreProtocol | None,
    *,
    policy: ChatPolicy | None = None,
) -> list[Message]:
    """Build the list of user-role messages for the requested slugs.

    Disabled skills are filtered out so a misbehaving client cannot
    bypass the toggle. Missing skills raise ``SkillError`` which the
    caller turns into a 400. Each enabled skill becomes one ``user``
    message; the chat endpoint places them right before the user's
    actual input so the model sees them as a consecutive block.
    Inline budgets come from ``policy``; ``None`` means the kernel
    defaults (16 KiB / 64 KiB).
    """
    if not skill_store:
        return []
    out: list[Message] = []
    for slug in slugs:
        s = await skill_store.get(slug)
        if s is None:
            raise SkillError(f"skill '{slug}' not found")
        if not s.enabled:
            continue
        # Inline file contents so the model can see scripts, templates,
        # and datasets that ship with the skill. Limited to a per-skill
        # budget so a chat request can't OOM by attaching a 100 MiB
        # bundle — budgets come from ``policy`` or the kernel
        # default dataclass.
        inlined = await _inline_skill_files(s, skill_store, policy=policy)
        out.append({"role": "user", "content": format_skill_message(inlined)})  # type: ignore[typeddict-item]
    return out


async def _inline_skill_files(
    skill,
    skill_store: SkillStoreProtocol,
    policy: ChatPolicy | None = None,
):
    """Return a copy of ``skill`` with file bodies inlined into body.

    Files are appended as fenced code blocks at the end of the body.
    Skill.files already lists every non-SKILL.md file relative to the
    skill root; we read each through ``skill_store.get_file`` which
    enforces the type allow-list + size cap so the loop is safe.
    The per-file and per-skill budgets come from ``policy`` (a
    :class:`ChatPolicy` injected by deploy) or fall back to the
    historical 16 KiB / 64 KiB defaults.
    """
    files = skill.files
    if not files:
        return skill
    pol = policy or ChatPolicy()
    chunks: list[str] = []
    used = 0
    for rel in files:
        if used >= pol.inline_skill_max_bytes:
            break
        try:
            ctype, data = await skill_store.get_file(skill.slug, rel)
        except SkillError:
            continue
        if len(data) > pol.inline_file_max_bytes:
            chunks.append(
                f"### `{rel}`\n\n(file omitted — exceeds {pol.inline_file_max_bytes // 1024} KiB inline limit)"
            )
            continue
        used += len(data)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            chunks.append(
                f"### `{rel}`\n\n(binary file, {len(data)} bytes — not inlined)"
            )
            continue
        chunks.append(f"### `{rel}`\n\n```{ctype}\n{text.rstrip()}\n```")
    if not chunks:
        return skill
    appended = "\n\n---\n\n## Attached file contents\n\n" + "\n\n".join(chunks)
    return Skill(**{**skill.__dict__, "body": (skill.body or "") + appended})


async def _event_stream(
    provider_name: str,
    model: str,
    messages: list[Message],
    store: ProviderStoreProtocol,
    *,
    session_id: str = "",
    stream: SessionStream | None = None,
    mcp_tools: list | None = None,
    tool_store: ToolStoreProtocol | None = None,
    active_tools: list | None = None,
    mcp_call_log: list[str] | None = None,
    manager_for_calls=None,
    session_store: SessionStoreProtocol | None = None,
    metrics_repo: MetricsRepositoryProtocol | None = None,
    chat_policy: ChatPolicy | None = None,
    tool_executor_registry: ToolExecutorRegistryProtocol | None = None,
    system_prompt_base: str | None = None,
) -> AsyncIterator[str]:
    """Yield SSE chunks for one chat call.

    When ``mcp_tools`` or ``active_tools`` is non-empty, we expose
    them to the LLM via the ``tools=`` parameter; if the model
    calls a tool, we execute it via the appropriate executor
    (MCPManager for MCP-namespaced tools, the local ToolStoreProtocol for
    plain tools), feed the result back into the conversation, and
    stream a second LLM response.

    Every event payload carries the ``session_id`` (echoed back from
    the request) plus a monotonic ``seq`` so the frontend can route
    events into the right per-session consumer even when many
    streams are in flight.

    Tool-call events use ``kind: "mcp" | "tool"`` so the frontend
    can colour / icon the capsule without parsing the namespaced
    ``name`` string. We emit ``execution_start`` / ``execution_end``
    around the batch of tool calls so the UI can render a
    'execution in progress' indicator.
    """
    seq = 0

    def _emit(event: str, data: dict[str, Any]) -> str:
        nonlocal seq
        seq += 1
        payload = {"session_id": session_id, "seq": seq, **data}
        return _sse(event, payload)

    async def _emit_delta(chunk: Any):
        """Emit one LLM delta as reasoning + content events.

        Providers (DeepSeek R1 / Qwen-R1 style) stream
        ``reasoning_content`` deltas BEFORE content deltas, so
        emitting reasoning first keeps the UI timeline
        chronological: thinking block, then reply text.
        """
        reasoning = getattr(chunk, "reasoning", None)
        if reasoning:
            yield _emit("reasoning", {"content": reasoning})
        content = getattr(chunk, "content", None)
        if content:
            yield _emit("chunk", {"content": content})

    provider = await store.get(provider_name)
    if provider is None:
        yield _emit("error", {"message": f"provider '{provider_name}' not found"})
        return
    # Extra request params for the selected model. Read from the
    # provider's ``model_params`` (provider-level) — model-level
    # ``models[].parameters`` would override per-model, but we keep
    # this build simple: provider-level wins for now.
    model_params = dict(getattr(provider, "model_params", None) or {})
    try:
        llm = build_provider(provider, model_override=model, model_params=model_params)
    except ValueError as e:
        yield _emit("error", {"message": str(e)})
        return

    logger.info(
        "chat.start provider=%s type=%s model=%s messages=%d tools=%d",
        provider_name,
        provider.provider_type,
        model or provider.default_model,
        len(messages),
        len(mcp_tools or []),
    )

    # Splice user-attached file paths into the user message bodies
    # exactly once. The augmented ``runtime_messages`` is what the
    # LLM sees; the original ``messages`` stays untouched so the
    # persist step at the end writes only metadata (reproducing
    # what the user typed, including on session reload). The
    # follow-up turn below uses ``runtime_messages`` too so the
    # assembled content is identical across loop iterations —
    # provider-side prompt caching can key on it.
    runtime_messages = _assemble_user_files(messages)

    llm_start = time.monotonic()
    try:
        all_tools: list[Any] = list(mcp_tools or []) + list(active_tools or [])
        llm_start = time.monotonic()
        llm_stream = await llm.chat(runtime_messages, tools=all_tools)
    except Exception as e:  # pragma: no cover — defensive
        logger.exception("chat.connect.error")
        # Record the failed call so the dashboard's error rate and
        # model_perf reflect it (otherwise ``query_ranking`` would
        # silently miss it — same root cause as mh-gateway's #85).
        await _record_llm(
            metrics_repo,
            session_id=session_id,
            provider=provider_name,
            model=model or provider.default_model,
            started_at=llm_start,
            final_response=None,
            cancelled=False,
        )
        yield _emit("error", {"message": f"connect failed: {e}"})
        return

    final_response = None
    # Accumulated plain-text assistant reply. We track this in
    # addition to the LLM's internal ``final_response.content`` so
    # that on cancellation (where ``aclose()`` discards the
    # provider's internal accumulator) we still have the content
    # the renderer has already shown. Both the renderer and the
    # backend persist this on cancel; either source of truth is
    # enough, but having both keeps the on-disk session and the
    # last-rendered bubble in sync.
    accumulated_assistant_text: str = ""
    # Per-call tool execution results. We keep these locally so a
    # cancel mid-tool still persists the partial tool outcome.
    accumulated_tool_calls: list[dict[str, Any]] = []

    async def _persist_partial(extra_assistant_text: str = "") -> None:
        """Write the current accumulated state to the session store.

        Called on every chunk (debounced internally) and on the
        terminal event (``done`` / ``cancelled`` / ``error``) so
        that closing the window mid-stream never loses the
        already-rendered content. Errors are swallowed — the
        next chunk's persist will retry, and the renderer also
        persists its own copy via the bus. ``messages`` here is
        the caller's ``messages`` list (which still includes the
        user turn); we append an assistant message when we have
        content."""
        if session_store is None or not session_id:
            return
        try:
            persisted: list[dict[str, Any]] = []
            for m in messages:
                persisted.append(
                    {
                        "role": m.get("role", "user"),
                        "content": m.get("content", ""),
                    }
                )
                for extra_key in ("skills", "mcp", "tools", "files"):
                    if extra_key in m:
                        persisted[-1][extra_key] = m[extra_key]
            assistant_text = accumulated_assistant_text + extra_assistant_text
            if assistant_text or accumulated_tool_calls:
                # Guard against double-append when the front-end
                # already persisted mid-stream.
                if (
                    persisted
                    and persisted[-1].get("role") == "assistant"
                    and persisted[-1].get("content") == assistant_text
                ):
                    pass  # already present
                else:
                    persisted.append(
                        {
                            "role": "assistant",
                            "content": assistant_text,
                            "tool_calls": list(accumulated_tool_calls)
                            if accumulated_tool_calls
                            else None,
                        }
                    )
            await session_store.update(session_id, {"messages": persisted})
        except Exception:
            logger.exception("chat.persist.failed sid=%s", session_id)

    try:
        async for chunk in llm_stream:
            if stream is not None and stream.cancel.is_set():
                # Cancellation signal from the registry. Tear down the
                # upstream stream without crashing the SSE response.
                logger.info(
                    "chat.cancel session=%s — aborting upstream stream",
                    session_id,
                )
                try:
                    await llm_stream.aclose()
                except Exception:
                    pass
                # Persist the partial assistant content BEFORE we
                # yield ``cancelled``. The renderer's bus debounced
                # persist runs 1.5 s after each chunk — a quick
                # window close mid-stream would otherwise lose
                # everything that just rendered. The backend is
                # the source of truth on disk, so the user's last
                # view is recoverable even if the renderer never
                # gets to flush.
                await _persist_partial()
                await _record_llm(
                    metrics_repo,
                    session_id=session_id,
                    provider=provider_name,
                    model=model or provider.default_model,
                    started_at=llm_start,
                    final_response=getattr(llm_stream, "response", None),
                    cancelled=True,
                )
                yield _emit(
                    "cancelled", {"assistant_message_id": stream.assistant_message_id}
                )
                return
            # Accumulate the chunk's content into our local mirror
            # so a cancel from this point forward still has the
            # text we've already yielded to the renderer.
            chunk_content = getattr(chunk, "content", None)
            if chunk_content:
                accumulated_assistant_text += chunk_content
            async for ev in _emit_delta(chunk):
                yield ev
        final_response = llm_stream.response
        await _record_llm(
            metrics_repo,
            session_id=session_id,
            provider=provider_name,
            model=model or provider.default_model,
            started_at=llm_start,
            final_response=final_response,
            cancelled=False,
        )
    except StreamStalledError as e:
        logger.warning("chat.stream.stalled")
        await _record_llm(
            metrics_repo,
            session_id=session_id,
            provider=provider_name,
            model=model or provider.default_model,
            started_at=llm_start,
            final_response=None,
            cancelled=False,
        )
        yield _emit("error", {"message": str(e)})
        return
    except Exception as e:  # pragma: no cover
        logger.exception("chat.stream.error")
        await _record_llm(
            metrics_repo,
            session_id=session_id,
            provider=provider_name,
            model=model or provider.default_model,
            started_at=llm_start,
            final_response=None,
            cancelled=False,
        )
        yield _emit("error", {"message": f"stream failed: {e}"})
        return

    # If the model called any tools, execute them and stream a
    # follow-up turn. Loop so a second (or Nth) tool call executes
    # like the first — e.g. the model listing a directory, then
    # reading a file. Every call the model emits gets executed; the
    # cap below only limits how many follow-up generations we run.
    # Dropping an emitted call looked like the model "stopping"
    # mid-turn (text cut off, no tool capsule) — never do that.
    pol = chat_policy or ChatPolicy()
    max_tool_rounds = pol.max_tool_rounds
    tool_round = 0
    conversation: list[Message] = list(runtime_messages)
    while True:
        tool_calls = list(getattr(final_response, "tool_calls", []) or [])
        if not tool_calls or (manager_for_calls is None and tool_store is None):
            break
        tool_round += 1
        # Build assistant + tool messages for the follow-up turn.
        tool_messages: list[Message] = []
        assistant_text = (final_response.content or "") if final_response else ""

        # Pre-compute the call ids so the ExecutionStart event can
        # carry the same set the UI will see in tool_start.
        call_ids: list[str] = []
        call_names: list[str] = []
        call_kinds: list[str] = []
        for tc in tool_calls:
            cid = f"call_{uuid.uuid4().hex[:12]}"
            name = tc["function"]["name"]
            kind = "mcp" if "::" in name else "tool"
            call_ids.append(cid)
            call_names.append(name)
            call_kinds.append(kind)
        yield _emit(
            "execution_start",
            {
                "call_ids": call_ids,
                "names": call_names,
                "kinds": call_kinds,
            },
        )

        for tc, call_id, name, kind in zip(
            tool_calls, call_ids, call_names, call_kinds
        ):
            args = _parse_tool_args(tc["function"]["arguments"])
            yield _emit(
                "tool_start",
                {
                    "call_id": call_id,
                    "kind": kind,
                    "name": name,
                    "args": args,
                },
            )

            text: str = ""
            error_msg: str | None = None
            tool_started_at = time.monotonic()
            try:
                if kind == "mcp":
                    # MCP path — the existing manager-based route.
                    slug, _, raw_name = name.partition("::")
                    if manager_for_calls is None:
                        raise MCPError("MCP subsystem not initialised for this request")
                    resolved_server = await manager_for_calls.store.get(slug)
                    if resolved_server is None:
                        raise MCPError(f"MCP server '{slug}' not attached to this run")
                    text = await manager_for_calls.manager.call_tool(
                        resolved_server, raw_name, args
                    )
                else:
                    # Plain Tool path — the kernel asks the deploy-
                    # provided :class:`ToolExecutorRegistryProtocol`
                    # for an executor for this kind. If no registry
                    # was wired the chat handler falls back to the
                    # historical :func:`build_tool_event_stream`
                    # path so ad-hoc / test apps without a registry
                    # keep working. Deploys that ship only ``local``
                    # tools don't need a registry; deploys with
                    # ``script`` / ``remote`` / custom kinds
                    # supply one and own the executor logic.
                    if tool_store is None:
                        raise MCPError("tool store not initialised for this request")
                    tool = await tool_store.get_by_model_name(name)
                    if tool is None:
                        tool = await tool_store.get(name)
                    if tool is None:
                        raise MCPError(f"tool '{name}' is not registered")
                    if not tool.enabled:
                        raise MCPError(f"tool '{name}' is disabled")
                    text_chunks: list[str] = []
                    cancel_evt = stream.cancel if stream is not None else None
                    executor: ToolExecutor | None = None
                    if tool_executor_registry is not None:
                        executor = tool_executor_registry.resolve(tool.kind)
                    if executor is not None:
                        # Deploy-provided strategy: run with the
                        # deploy's chat policy timeout + cancel
                        # signal. The executor yields chunks through
                        # ``execute()`` — we read them as they arrive
                        # to keep the progress UX.
                        execution = None
                        try:
                            execution = await executor.execute(
                                tool,
                                args,
                                cancel_event=cancel_evt,
                                timeout=pol.tool_timeout_seconds,
                            )
                            # ``execute`` already collected the
                            # chunks into ``ToolExecution.chunks``;
                            # we still want to forward each one as
                            # a progress event so the renderer can
                            # show streaming output. The executor's
                            # interface returns them as a list rather
                            # than an async iterator (chat handler
                            # emits ``tool_progress`` events from the
                            # list to keep the wire format stable).
                            for chunk in execution.chunks:
                                text_chunks.append(chunk)
                                yield _emit(
                                    "tool_progress",
                                    {
                                        "call_id": call_id,
                                        "kind": kind,
                                        "name": name,
                                        "chunk": chunk,
                                    },
                                )
                            if not execution.ok:
                                err = execution.error
                                raise MCPError(err or "tool failed")
                            if execution.cancelled:
                                raise asyncio.CancelledError("tool cancelled by user")
                        except asyncio.CancelledError:
                            raise
                        except MCPError:
                            raise
                        except Exception as e:
                            raise MCPError(str(e)) from e
                    else:
                        # No deploy executor for this kind — fall
                        # back to the kernel's local-callable
                        # helper (``run_tool`` inside
                        # ``build_tool_event_stream``). This
                        # preserves the original behaviour for
                        # local/bundled tools when the deploy
                        # doesn't bring its own executor.
                        async for chunk in build_tool_event_stream(
                            tool,
                            args,
                            cancel_event=cancel_evt,
                            timeout=pol.tool_timeout_seconds,
                        ):
                            text_chunks.append(chunk)
                            # Stream progress chunks as they arrive so
                            # the UI can show a partial result.
                            yield _emit(
                                "tool_progress",
                                {
                                    "call_id": call_id,
                                    "kind": kind,
                                    "name": name,
                                    "chunk": chunk,
                                },
                            )
                    text = "".join(text_chunks)
            except asyncio.CancelledError:
                # User-driven cancel via the registry. Re-raise so
                # the outer loop can also tear down its LLM stream
                # if it's still open.
                await _record_tool(
                    metrics_repo,
                    session_id=session_id,
                    name=name,
                    started_at=tool_started_at,
                    ok=False,
                    error="cancelled",
                )
                yield _emit(
                    "tool_end",
                    {
                        "call_id": call_id,
                        "kind": kind,
                        "name": name,
                        "ok": False,
                        "result": "",
                        "error": "cancelled",
                        "cancelled": True,
                    },
                )
                yield _emit(
                    "execution_end",
                    {"ok": False, "cancelled": True, "count": len(tool_calls)},
                )
                raise
            except Exception as e:
                # The tool raised something. Make the message *useful*
                # to the model: name the tool, name the error class,
                # include the exception text, and end with a hint
                # about whether retrying helps or the call is a
                # permanent failure. A bare ``f"[tool error] {e}"``
                # leaves the model guessing.
                import traceback as _tb

                logger.error(
                    "chat.tool.exception tool=%s\n%s",
                    name,
                    _tb.format_exc(),
                )
                err_class = type(e).__name__
                raw = str(e).strip() or "(no message)"
                hint = _tool_error_hint(err_class, raw)
                text = f"[tool error] tool='{name}' class={err_class}: {raw}" + (
                    f"\nhint: {hint}" if hint else ""
                )
                error_msg = text
                await _record_tool(
                    metrics_repo,
                    session_id=session_id,
                    name=name,
                    started_at=tool_started_at,
                    ok=False,
                    error=f"{err_class}: {raw}",
                )

            if mcp_call_log is not None:
                mcp_call_log.append(name)
            yield _emit(
                "tool_end",
                {
                    "call_id": call_id,
                    "kind": kind,
                    "name": name,
                    "ok": error_msg is None,
                    "result": text,
                    "error": error_msg,
                },
            )
            if error_msg is None:
                await _record_tool(
                    metrics_repo,
                    session_id=session_id,
                    name=name,
                    started_at=tool_started_at,
                    ok=True,
                )
            tool_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": text,
                }
            )
        yield _emit(
            "execution_end",
            {"ok": True, "cancelled": False, "count": len(tool_calls)},
        )

        # Continue the conversation: prior messages + the assistant
        # message that initiated the tool calls + the tool results.
        # ``runtime_messages`` (not ``messages``) so the assembled
        # file-block content from the first turn is preserved
        # verbatim into the follow-up turn — the model's prompt
        # cache key stays stable.
        conversation.append(
            {
                "role": "assistant",
                "content": assistant_text,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        },
                    }
                    for tc in tool_calls
                ],
            }
        )
        conversation.extend(tool_messages)
        if tool_round >= max_tool_rounds:
            logger.warning("chat.tool.max_rounds reached=%d", max_tool_rounds)
            # Every call the model asked for has now executed; stop
            # asking it for another round instead of generating one
            # we'd have to drop.
            break
        llm2_start = time.monotonic()
        try:
            # Follow-up turn — keep the tool schemas so the model
            # can emit a structured tool call on the next round.
            # Without them DeepSeek falls back to DSML text, which
            # no parser understands and the UI shows as literal tags.
            llm2_start = time.monotonic()
            llm_stream2 = await llm.chat(conversation, tools=all_tools)
        except Exception as e:  # pragma: no cover
            logger.exception("chat.tool.followup.error")
            await _record_llm(
                metrics_repo,
                session_id=session_id,
                provider=provider_name,
                model=model or provider.default_model,
                started_at=llm2_start,
                final_response=None,
                cancelled=False,
            )
            yield _emit("error", {"message": f"follow-up chat failed: {e}"})
            return
        try:
            async for chunk in llm_stream2:
                if stream is not None and stream.cancel.is_set():
                    try:
                        await llm_stream2.aclose()
                    except Exception:
                        pass
                    await _record_llm(
                        metrics_repo,
                        session_id=session_id,
                        provider=provider_name,
                        model=model or provider.default_model,
                        started_at=llm2_start,
                        final_response=getattr(llm_stream2, "response", None),
                        cancelled=True,
                    )
                    yield _emit(
                        "cancelled",
                        {"assistant_message_id": stream.assistant_message_id},
                    )
                    return
                chunk_content = getattr(chunk, "content", None)
                if chunk_content:
                    accumulated_assistant_text += chunk_content
                async for ev in _emit_delta(chunk):
                    yield ev
            final_response = llm_stream2.response
            await _record_llm(
                metrics_repo,
                session_id=session_id,
                provider=provider_name,
                model=model or provider.default_model,
                started_at=llm2_start,
                final_response=final_response,
                cancelled=False,
            )
        except StreamStalledError as e:
            logger.warning("chat.stream.stalled")
            await _record_llm(
                metrics_repo,
                session_id=session_id,
                provider=provider_name,
                model=model or provider.default_model,
                started_at=llm2_start,
                final_response=None,
                cancelled=False,
            )
            yield _emit("error", {"message": str(e)})
            return

    payload: dict[str, Any] = {}
    if final_response is not None and getattr(final_response, "usage", None):
        payload["usage"] = final_response.usage
    yield _emit("done", payload)

    # Persist the post-stream view into the session store so a
    # window close mid-stream or a reload after the stream ends
    # sees the same content the renderer just streamed. We do this
    # server-side as the source of truth: even if the frontend's
    # debounced persist never lands, the session on disk has the
    # assistant's reply. The original user message's metadata
    # (skills/mcp/tools) is preserved as-is so a reload reconstructs
    # exactly what the user sent.
    if final_response is not None and getattr(final_response, "tool_calls", None):
        # We append the provider's final tool calls to our
        # accumulator so the persisted assistant message carries
        # the structured tool_calls the renderer also collects
        # from ``tool_start`` events.
        for tc in final_response.tool_calls or []:
            accumulated_tool_calls.append(tc)
    await _persist_partial()


def _parse_tool_args(raw: Any) -> dict[str, Any]:
    """The LLM returns tool args as a JSON string. Be permissive: empty
    / non-JSON → empty dict so a broken call still reaches the tool."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            import json

            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {"_raw": parsed}
        except Exception:
            return {"_raw": raw}
    return {}


# Heuristic hint the model can act on. Returns a short instruction
# string for the model, or '' when the exception already explains
# itself. Kept inline (not config) because the rules are tight and
# adding a config layer is overhead for a constant.
def _tool_error_hint(err_class: str, msg: str) -> str:
    m = msg.lower()
    if "callable is required" in m or "is not loaded" in m:
        # Tool source wasn't loaded into this backend process. Most
        # common cause: bulk-import on a hot-reloaded worker, or the
        # tool was deleted while a chat was in flight. The model
        # can't fix this — surface it clearly so the user (not the
        # model) can re-import or restart.
        return (
            "backend did not load this tool's source. "
            "Tell the user to delete + re-import the tool, or restart the backend."
        )
    if err_class == "TimeoutError" or "did not finish within" in m:
        return (
            "the tool hit its timeout. Retry with a larger `timeout` "
            "argument (hard cap 600s) or split the work into smaller calls."
        )
    if err_class == "FileNotFoundError" or "no such file" in m:
        return (
            "the executable the tool tried to run is missing. "
            "Check PATH / installation; this is permanent until the user fixes it."
        )
    if err_class in ("PermissionError",) or "access is denied" in m:
        return (
            "permission denied. The command needs elevated rights; "
            "this is not fixable from the tool call itself."
        )
    if err_class == "ConnectionError" or "connect" in m and "refused" in m:
        return "could not reach a service. Check the target is running and reachable."
    if err_class == "ValueError":
        # Bad arguments. The model can usually fix this from the
        # message alone — no extra hint needed.
        return ""
    return ""  # unknown: let the exception message speak for itself


async def _record_llm(
    metrics_repo: MetricsRepositoryProtocol | None,
    *,
    session_id: str,
    provider: str,
    model: str,
    started_at: float,
    final_response: Any,
    cancelled: bool,
) -> None:
    """Persist one LLM call's metrics.

    Called at the end of every streamed response (success,
    cancelled, error). ``final_response`` may be ``None`` when the
    LLM failed before producing a response object — token counts
    come back as 0 in that case.

    Never raises: a metrics failure must NOT break the chat
    handler. We log + swallow.
    """
    if metrics_repo is None:
        return
    duration_ms = round((time.monotonic() - started_at) * 1000, 2)
    usage = getattr(final_response, "usage", None) or {}
    prompt_tokens = (
        int(usage.get("prompt_tokens") or 0) if isinstance(usage, dict) else 0
    )
    completion_tokens = (
        int(usage.get("completion_tokens") or 0) if isinstance(usage, dict) else 0
    )
    status = "ok"
    if cancelled:
        status = "cancelled"
    elif final_response is None:
        status = "error"
    try:
        await metrics_repo.record_llm_call(
            LLMCallRecord(
                ts=_now_iso(),
                session_id=session_id,
                provider=provider,
                model=model or "",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                duration_ms=duration_ms,
                status=status,
                cancelled=cancelled,
            )
        )
    except Exception:  # pragma: no cover — defensive
        logger.exception("metrics.record_llm.failed session=%s", session_id)


async def _record_tool(
    metrics_repo: MetricsRepositoryProtocol | None,
    *,
    session_id: str,
    name: str,
    started_at: float,
    ok: bool,
    error: str = "",
) -> None:
    if metrics_repo is None:
        return
    duration_ms = round((time.monotonic() - started_at) * 1000, 2)
    try:
        await metrics_repo.record_tool_call(
            ToolCallRecord(
                ts=_now_iso(),
                session_id=session_id,
                kind="tool",
                name=name,
                duration_ms=duration_ms,
                status="ok" if ok else "error",
                error=error,
            )
        )
    except Exception:  # pragma: no cover
        logger.exception("metrics.record_tool.failed session=%s", session_id)


def _sse(event: str, data: dict[str, Any]) -> str:
    import json

    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("")
async def chat(
    body: dict[str, Any],
    request: Request,
    store: ProviderStoreProtocol = Depends(get_store),
    registry: StreamRegistryProtocol = Depends(get_registry),
) -> StreamingResponse:
    provider_name = (body.get("provider") or "").strip()
    if not provider_name:
        raise HTTPException(status_code=400, detail="provider is required")
    model = (body.get("model") or "").strip()

    raw_messages = body.get("messages") or []
    if not isinstance(raw_messages, list) or not raw_messages:
        raise HTTPException(status_code=400, detail="messages must be a non-empty list")

    # Read deploy-injected state once per request — chat policy,
    # tool-executor registry, system-prompt base override. The
    # helpers that take ``request`` (e.g. ``get_prefs_store``)
    # already pull what they need; these top-level kwargs go
    # straight through to ``_event_stream``.
    chat_policy: ChatPolicy = (
        getattr(request.app.state, "chat_policy", None) or ChatPolicy()
    )
    tool_executor_registry: ToolExecutorRegistryProtocol | None = getattr(
        request.app.state, "tool_executor_registry", None
    )
    system_prompt_base: str | None = getattr(
        request.app.state, "system_prompt_base", None
    )

    messages = _coerce_messages(raw_messages)
    session_id = (body.get("session_id") or "").strip()
    assistant_message_id = (body.get("assistant_message_id") or "").strip()
    # Lift the per-message metadata (skills / mcp / tools) off the
    # request payload so we can preserve it on persistence later.
    # ``_coerce_messages`` only carries role+content; the metadata
    # was stripped. We splice it back here so the same dicts land
    # in the session store.
    _attach_user_metadata(messages, raw_messages)
    session_store: SessionStoreProtocol | None = get_session_store(request)

    # System prompt is assembled server-side from a fixed base (the
    # facts the runtime needs the model to know — skill root, cwd
    # discipline, etc.) plus the user's saved addition. The client no
    # longer sends a system_prompt field: keeping the base authoritative
    # on the server prevents the user from accidentally erasing
    # critical information when they edit their addition. The base
    # itself is deploy-injectable via ``system_prompt_base``.
    prefs_store: PrefsStoreProtocol | None = get_prefs_store(request)
    user_addition = ""
    if prefs_store is not None:
        try:
            user_addition = (await prefs_store.get()).system_prompt_addition
        except (
            Exception
        ):  # pragma: no cover — defensive: a broken prefs file shouldn't kill chat
            logger.exception("prefs.read failed; sending base-only prompt")
    messages = [
        {
            "role": "system",
            "content": _build_system_prompt(
                user_addition, base_override=system_prompt_base
            ),
        },
        *messages,
    ]

    # Skill injection. Skills are sent as user-role messages, NOT
    # folded into the system prompt. We resolve them now (validates
    # slugs, filters disabled, inlines attached file contents) and
    # splice them in right before the user's current input below.
    raw_skills = body.get("skills") or []
    if not isinstance(raw_skills, list):
        raise HTTPException(status_code=400, detail="skills must be a list of slugs")

    # Build the per-skill user messages. Skills are user-role
    # messages, NOT system prompt — they ship with the conversation
    # as ephemeral context that the user has explicitly attached.
    # We insert them right before the user's actual current input so
    # the model sees the "skill messages + user input" block as the
    # latest exchange. Inline budgets come from ``chat_policy``.
    skill_store = get_skill_store(request)
    try:
        skill_messages = await _resolve_skill_messages(
            raw_skills, skill_store, policy=chat_policy
        )
    except SkillError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None

    if skill_messages:
        # The last message is the user's current input. Place skill
        # messages immediately before it. If for some reason the last
        # message isn't a user role (defensive — should never happen),
        # append skills to the end so they still ship.
        if messages and messages[-1].get("role") == "user":
            history = messages[:-1]
            current_input = messages[-1]
            messages = [*history, *skill_messages, current_input]
        else:
            messages = [*messages, *skill_messages]
        logger.info(
            "chat.skills provider=%s skills=%s",
            provider_name,
            ",".join(str(s) for s in raw_skills),
        )

    # MCP tool wiring. Tools from attached MCPs are exposed to the LLM
    # via the standard tools= parameter; the manager proxies tool_calls
    # back to the subprocess and feeds results into a follow-up turn.
    raw_mcps = body.get("mcp") or []
    if not isinstance(raw_mcps, list):
        raise HTTPException(status_code=400, detail="mcp must be a list of slugs")
    mcp_store = get_mcp_store(request)
    mcp_manager = get_mcp_manager(request)
    mcp_tools: list[Any] = []
    mcp_errors: list[str] = []
    if raw_mcps:
        try:
            if mcp_store is None or mcp_manager is None:
                raise MCPError("MCP subsystem not initialized")
            mcp_tools, mcp_errors = await collect_mcp_tools(
                mcp_manager, mcp_store, raw_mcps
            )
        except MCPError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        if raw_mcps:
            logger.info(
                "chat.mcp provider=%s mcps=%s tools=%d",
                provider_name,
                ",".join(str(s) for s in raw_mcps),
                len(mcp_tools),
            )
        if mcp_errors:
            logger.warning(
                "chat.mcp.errors provider=%s errors=%s", provider_name, mcp_errors
            )

    # Register the stream FIRST so the per-session cancel event is
    # available when we build the StreamingTools below — each
    # StreamingTool's wrapper checks the cancel event between
    # chunk yields so a stop button interrupts long-running tools.
    stream: SessionStream | None = None
    if session_id:
        stream = await registry.register(session_id)
        stream.assistant_message_id = assistant_message_id

    # ── Usage metrics: record each attached skill / MCP as a
    # ToolCallRecord(kind="skill"|"mcp"). Counts per *attachment*
    # (which skills / MCP servers the user reaches for), not per
    # internal tool call — the ranking the user asked for is at the
    # server / skill level, not at the per-tool-name level.
    metrics_repo = get_metrics_repo(request)
    if metrics_repo is not None:
        attached_skills: list[str] = raw_skills if isinstance(raw_skills, list) else []
        attached_mcps: list[str] = raw_mcps if isinstance(raw_mcps, list) else []
        for slug in attached_skills:
            try:
                await metrics_repo.record_tool_call(
                    ToolCallRecord(
                        ts=_now_iso(),
                        session_id=session_id,
                        kind="skill",
                        name=str(slug),
                        status="ok",
                    )
                )
            except Exception:  # pragma: no cover — metrics never block chat
                logger.exception("metrics.record_skill.failed slug=%s", slug)
        for slug in attached_mcps:
            ok = True
            err = ""
            if mcp_errors:
                # ``collect_mcp_tools`` pairs per-slug errors; surface
                # the first matching one to the dashboard.
                for line in mcp_errors:
                    if isinstance(line, str) and line.startswith(str(slug)):
                        ok = False
                        err = line
                        break
            try:
                await metrics_repo.record_tool_call(
                    ToolCallRecord(
                        ts=_now_iso(),
                        session_id=session_id,
                        kind="mcp",
                        name=str(slug),
                        status="ok" if ok else "error",
                        error=err,
                    )
                )
            except Exception:  # pragma: no cover
                logger.exception("metrics.record_mcp.failed slug=%s", slug)

    # Carry an MCP runner object through to the event stream so the
    # follow-up turn can resolve (slug → MCPServer) and forward tool
    # calls back to the right subprocess.
    class _MCPRunner:
        def __init__(self, store: Any, manager: Any) -> None:
            self.store = store
            self.manager = manager

    mcp_runner = _MCPRunner(mcp_store, mcp_manager) if mcp_tools else None
    mcp_call_log: list[str] = []

    # Tools wiring — separate from MCP. Each requested tool is
    # resolved through the ToolStoreProtocol and wrapped in a
    # StreamingTool. The LLM provider accepts any object with a
    # ``to_schema`` method, so StreamingTool slots in next to
    # MCPSchemaTool on the ``tools=`` parameter without ceremony.
    raw_tools = body.get("tools") or []
    if not isinstance(raw_tools, list):
        raise HTTPException(status_code=400, detail="tools must be a list of slugs")
    tool_store = get_tool_store(request)
    active_tools: list[Any] = []
    if raw_tools:
        if tool_store is None:
            raise HTTPException(status_code=503, detail="tool store not initialized")
        for slug in raw_tools:
            tool = await tool_store.get(str(slug))
            if tool is None:
                raise HTTPException(status_code=400, detail=f"tool '{slug}' not found")
            if not tool.enabled:
                continue
            cancel_evt = stream.cancel if stream is not None else None
            # ``build_streaming_tool`` consults the deploy's
            # :class:`ToolExecutorRegistryProtocol` when one is
            # wired (the registry decides how each ``tool.kind`` is
            # actually executed). Without a registry it falls back
            # to the historical kernel-local helper, which works
            # for ``local``/``bundled`` tools and stubs
            # ``script``/``remote`` the way the original code did.
            timeout_s = (
                chat_policy.tool_timeout_seconds
                if chat_policy is not None
                else DEFAULT_TOOL_TIMEOUT_SECONDS
            )
            active_tools.append(
                await build_streaming_tool(
                    tool,
                    cancel_event=cancel_evt,
                    timeout=timeout_s,
                    tool_executor_registry=tool_executor_registry,
                )
            )
        logger.info(
            "chat.tools provider=%s tools=%s resolved=%d",
            provider_name,
            ",".join(str(s) for s in raw_tools),
            len(active_tools),
        )

    async def on_disconnect() -> None:
        """Triggered when the client closes the connection without
        asking for cancellation (page closed, switched session,
        navigation). Just signal cancel — the chunk loop checks the
        flag and emits ``cancelled`` before tearing down.
        """
        if stream is not None:
            stream.cancel.set()

    async def event_iter() -> AsyncIterator[str]:
        try:
            async for chunk in _event_stream(
                provider_name,
                model,
                messages,
                store,
                session_id=session_id,
                stream=stream,
                mcp_tools=mcp_tools,
                tool_store=tool_store,
                active_tools=active_tools,
                mcp_call_log=mcp_call_log,
                manager_for_calls=mcp_runner,
                session_store=session_store,
                metrics_repo=get_metrics_repo(request),
                chat_policy=chat_policy,
                tool_executor_registry=tool_executor_registry,
                system_prompt_base=system_prompt_base,
            ):
                yield chunk
        finally:
            if stream is not None:
                if not stream.done.done():
                    stream.done.set_result(None)
                await registry.unregister(session_id)

    return StreamingResponse(
        event_iter(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.post("/cancel/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_session(
    session_id: str,
    registry: StreamRegistryProtocol = Depends(get_registry),
) -> None:
    """Ask the running stream for this session to stop. The chunk loop
    notices the cancel flag and emits a ``cancelled`` event, then
    the SSE connection closes. Idempotent — a session with no running
    stream just gets a no-op 204."""
    stream = registry.get(session_id)
    if stream is not None:
        stream.cancel.set()
        stream.cancelled = True
