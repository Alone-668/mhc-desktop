"""End-to-end tests for the user-attached-files feature.

Covers:

* ``_assemble_user_files`` splices the file paths into user-message
  content as a plain-text block and does NOT touch the original
  messages list.
* The block is stable across two consecutive calls — the second
  call yields the same augmented content (idempotent; matches what
  the prompt cache needs).
* Non-user messages are passed through unchanged.
* Messages without ``files`` are passed through unchanged (cheap
  no-op when no files attached).
* The ``_attach_user_metadata`` whitelist now carries ``files`` so
  a payload like ``{"role": "user", "content": "...", "files": [...]}``
  survives the coerce step.
* The chat endpoint round-trips ``files`` through persistence
  metadata (the assemble happens separately, just before the LLM
  call, so persistence sees metadata-only).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


# Import the chat module by file path so we can exercise the
# private helpers without spinning up FastAPI.
CHAT_PY = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "mhc_desktop_backend"
    / "api"
    / "chat.py"
)
spec = importlib.util.spec_from_file_location("mhc_chat_under_test", CHAT_PY)
chat_mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["mhc_chat_under_test"] = chat_mod
spec.loader.exec_module(chat_mod)


_FORMAT = chat_mod._format_files_block
_ASSEMBLE = chat_mod._assemble_user_files
_COERCE = chat_mod._coerce_messages
_ATTACH = chat_mod._attach_user_metadata


# ── _format_files_block ────────────────────────────────────────────


def test_format_files_block_single_file_includes_path_and_directive():
    block = _FORMAT(
        [{"name": "foo.txt", "path": r"C:\Users\alice\foo.txt", "size": 1234}]
    )
    # Directive phrasing that links the user's "this" / "it" pronouns
    # to the attached file.
    assert "When the user asks about" in block
    assert '"this"' in block
    assert r"path: C:\Users\alice\foo.txt" in block
    assert "size: 1234 B" in block
    assert "name: foo.txt" in block


def test_format_files_block_multi_file_is_numbered():
    block = _FORMAT(
        [
            {"name": "foo.txt", "path": r"C:\Users\alice\foo.txt", "size": 1234},
            {"name": "bar.md", "path": "/home/alice/bar.md", "size": 5678},
        ]
    )
    assert "2 files" in block
    assert "file 1:" in block
    assert "file 2:" in block
    assert r"path: C:\Users\alice\foo.txt" in block
    assert "path: /home/alice/bar.md" in block


def test_format_files_block_handles_path_only_entry():
    block = _FORMAT([{"path": "/tmp/loose", "size": 10}])
    # No name — the line shows "(unnamed)" so the model still sees
    # an attachment exists, rather than the entry being silently
    # dropped.
    assert "(unnamed)" in block
    assert "path: /tmp/loose" in block


def test_format_files_block_handles_unknown_size():
    block = _FORMAT([{"name": "x.txt", "path": "/x", "size": "not-a-number"}])
    assert "size: ? B" in block


def test_format_files_block_empty_path_still_emits_a_line():
    """An attachment with no absolute path must NOT be silently
    dropped — the model needs to know the file exists so it can
    ask the user. The line carries the name + a clear "missing
    path" marker."""
    block = _FORMAT([{"name": "browser-pick.txt", "path": "", "size": 0}])
    assert "name: browser-pick.txt" in block
    assert "(no absolute path" in block


def test_format_files_block_deterministic_for_same_input():
    a = _FORMAT([{"name": "a.txt", "path": "/a", "size": 10}])
    b = _FORMAT([{"name": "a.txt", "path": "/a", "size": 10}])
    assert a == b


# ── _assemble_user_files ──────────────────────────────────────────


def test_assemble_appends_block_to_user_content():
    files = [{"name": "a.txt", "path": "/a", "size": 10}]
    src = [{"role": "user", "content": "summarize", "files": files}]
    out = _ASSEMBLE(src)
    assert out is not src
    assert src[0]["content"] == "summarize"  # original untouched
    assert "summarize" in out[0]["content"]
    assert "[Attached files" in out[0]["content"]
    assert "path: /a" in out[0]["content"]
    # metadata survives so callers can still inspect it
    assert out[0]["files"] is files


def test_assemble_pure_files_only_no_user_text():
    """User attached files but typed nothing — the block becomes
    the entire message body."""
    files = [{"name": "only.txt", "path": "/only", "size": 1}]
    src = [{"role": "user", "content": "", "files": files}]
    out = _ASSEMBLE(src)
    assert out[0]["content"].startswith("[Attached files")


def test_assemble_leaves_non_user_messages_alone():
    files = [{"name": "a.txt", "path": "/a", "size": 10}]
    src = [
        {"role": "system", "content": "be helpful", "files": files},
        {"role": "assistant", "content": "ok", "files": files},
    ]
    out = _ASSEMBLE(src)
    # No content augmentation for non-user roles — system + assistant
    # content is left exactly as-is. The metadata dict entry is
    # passed through unchanged (we just don't splice anything into
    # their content); the LLM never reads non-user messages' files
    # because there are none in practice.
    assert out[0]["content"] == "be helpful"
    assert out[1]["content"] == "ok"
    assert "[Attached files" not in out[0]["content"]
    assert "[Attached files" not in out[1]["content"]


def test_assemble_is_noop_when_no_files_anywhere():
    src = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    out = _ASSEMBLE(src)
    # When there's nothing to do, return the original list (cheap
    # call-site check: ``if out is messages`` stays True so callers
    # can skip a follow-up copy if they wanted).
    assert out is src


def test_assemble_is_idempotent_across_two_calls():
    """Two consecutive calls produce identical output. This is the
    invariant the controller's loop relies on — the same user
    message is sent to the LLM in turn 1 AND turn N without
    re-inlining the path block twice."""
    files = [{"name": "a.txt", "path": "/a", "size": 10}]
    src = [{"role": "user", "content": "look", "files": files}]
    first = _ASSEMBLE(src)
    second = _ASSEMBLE(src)
    # The augmented content is byte-identical between calls.
    assert first[0]["content"] == second[0]["content"]
    # And it's identical between turn 1 and a *second* assemble that
    # mirrors the follow-up turn (re-assembling from the same input
    # is what the loop does).
    third = _ASSEMBLE([{"role": "user", "content": "look", "files": files}])
    assert first[0]["content"] == third[0]["content"]


def test_assemble_does_not_mutate_source_list():
    files = [{"name": "a.txt", "path": "/a", "size": 10}]
    src = [{"role": "user", "content": "look", "files": files}]
    snapshot = (src[0]["content"], list(src[0]["files"]))
    _ASSEMBLE(src)
    _ASSEMBLE(src)  # run twice
    assert (src[0]["content"], list(src[0]["files"])) == snapshot


# ── _coerce_messages + _attach_user_metadata whitelist ────────────


def test_coerce_then_attach_preserves_files_metadata():
    raw = [
        {
            "role": "user",
            "content": "hi",
            "files": [{"name": "a.txt", "path": "/a", "size": 1}],
        }
    ]
    coerced = _COERCE(raw)
    # Metadata is spliced during the same pass as coercion (filtering a
    # malformed message would otherwise shift zip-based re-pairing); the
    # legacy attach step is a no-op and must not drop it.
    assert coerced[0]["files"] == [{"name": "a.txt", "path": "/a", "size": 1}]
    _ATTACH(coerced, raw)
    assert coerced[0]["files"] == [{"name": "a.txt", "path": "/a", "size": 1}]
    # After assembly, the file paths show up in the augmented content
    # without losing the metadata.
    runtime = _ASSEMBLE(coerced)
    assert "path: /a" in runtime[0]["content"]
    assert runtime[0]["files"] == [{"name": "a.txt", "path": "/a", "size": 1}]


def test_coerce_drops_empty_assistant_keeps_tool_calls():
    """Empty assistant messages (no content, no tool_calls) are the
    400 'content or tool_calls must be set' trigger — they must be
    filtered, while an assistant that carries tool_calls (even with
    empty text) survives WITH its tool_calls, and tool messages keep
    their tool_call_id. No position-shift bugs from filtering."""
    raw = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": ""},  # dirty history
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call_1", "function": {"name": "f", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        {"role": "user", "content": "next"},
    ]
    out = _COERCE(raw)
    assert len(out) == 4
    # the dirty empty assistant is gone
    assert not any(
        m["role"] == "assistant"
        and not str(m.get("content", "")).strip()
        and not m.get("tool_calls")
        for m in out
    )
    # the tool-calling assistant kept its tool_calls, paired correctly
    asst = [m for m in out if m["role"] == "assistant"][0]
    assert asst.get("tool_calls") == [{"id": "call_1", "function": {"name": "f", "arguments": "{}"}}]
    # the tool message kept its tool_call_id
    tool = [m for m in out if m["role"] == "tool"][0]
    assert tool.get("tool_call_id") == "call_1"


def test_multiple_users_with_files_all_get_assembled():
    """Each user message that has files must be augmented
    independently — assembling the LAST one only would be a bug
    because the controller loop replays the full history."""
    src = [
        {
            "role": "user",
            "content": "first",
            "files": [{"name": "a", "path": "/a", "size": 1}],
        },
        {"role": "assistant", "content": "ack"},
        {
            "role": "user",
            "content": "second",
            "files": [{"name": "b", "path": "/b", "size": 2}],
        },
    ]
    out = _ASSEMBLE(src)
    assert "path: /a" in out[0]["content"]
    assert "path: /b" in out[2]["content"]
    assert "first" in out[0]["content"]
    assert "second" in out[2]["content"]
    # The assistant turn stays a plain echo.
    assert out[1]["content"] == "ack"
