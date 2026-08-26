"""The file-tools content-pack tools must keep working as distributed.

Loads the real tool.py files from content-packs and exercises the
same contract the chat layer relies on: string chunks, semantic
error prefixes ([error:bad-arg] / [error]), pagination hints, and
no crashes on edge inputs. Ported from the mh-gateway
builtin_agents/local_tools.py implementations (read_file /
write_file / append_file / edit_file) into the desktop tool format.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PACK_ROOT = (
    Path(__file__).resolve().parents[2] / "mhc-desktop-app" / "content-packs" / "tools"
)


def _load(slug: str):
    spec = importlib.util.spec_from_file_location(
        f"file_tool_{slug}", PACK_ROOT / slug / "tool.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def read_tool():
    return _load("read-file")


@pytest.fixture(scope="module")
def write_tool():
    return _load("write-file")


@pytest.fixture(scope="module")
def append_tool():
    return _load("append-file")


@pytest.fixture(scope="module")
def edit_tool():
    return _load("edit-file")


async def collect(coro) -> list[str]:
    out: list[str] = []
    async for chunk in coro:
        out.append(chunk)
    return out


# ── read-file ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_read_file_returns_content(tmp_path: Path, read_tool):
    f = tmp_path / "a.txt"
    f.write_text("line1\nline2\nline3\n", encoding="utf-8")
    out = await collect(read_tool.tool_run(path=str(f)))
    assert "".join(out) == "line1\nline2\nline3\n"


@pytest.mark.asyncio
async def test_read_file_pages_and_marks_truncated(tmp_path: Path, read_tool):
    f = tmp_path / "big.txt"
    f.write_text("".join(f"line{i}\n" for i in range(10)), encoding="utf-8")
    out = await collect(read_tool.tool_run(path=str(f), offset=1, limit=3))
    text = "".join(out)
    assert text.startswith("line0\nline1\nline2\n")
    assert "[truncated]" in text
    assert "offset=4" in text  # tells the model where to continue


@pytest.mark.asyncio
async def test_read_file_limit_zero_no_truncation(tmp_path: Path, read_tool):
    f = tmp_path / "big.txt"
    f.write_text("".join(f"line{i}\n" for i in range(10)), encoding="utf-8")
    out = await collect(read_tool.tool_run(path=str(f), limit=0))
    text = "".join(out)
    assert text.startswith("line0\n") and "line9\n" in text
    assert "[truncated]" not in text


@pytest.mark.asyncio
async def test_read_file_missing_file(tmp_path: Path, read_tool):
    out = await collect(read_tool.tool_run(path=str(tmp_path / "nope.txt")))
    assert out[0].startswith("[error] file not found:")


@pytest.mark.asyncio
async def test_read_file_bad_args(read_tool):
    out = await collect(read_tool.tool_run(path=""))
    assert out[0].startswith("[error:bad-arg]")


# ── write-file ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_write_file_creates_and_overwrites(tmp_path: Path, write_tool):
    f = tmp_path / "out.txt"
    out = await collect(write_tool.tool_run(path=str(f), content="hello\n"))
    assert "".join(out).startswith("Wrote 6 characters")
    assert f.read_text(encoding="utf-8") == "hello\n"
    # Overwrite
    await collect(write_tool.tool_run(path=str(f), content="world\n"))
    assert f.read_text(encoding="utf-8") == "world\n"


@pytest.mark.asyncio
async def test_write_file_creates_parent_dirs(tmp_path: Path, write_tool):
    f = tmp_path / "a" / "b" / "c.txt"
    out = await collect(write_tool.tool_run(path=str(f), content="x"))
    text = "".join(out)
    assert "created parent directory" in text
    assert f.read_text(encoding="utf-8") == "x"


@pytest.mark.asyncio
async def test_write_file_bad_args(write_tool):
    out = await collect(write_tool.tool_run(path="", content="x"))
    assert out[0].startswith("[error:bad-arg]")
    out = await collect(write_tool.tool_run(path="ok.txt", content=123))
    assert out[0].startswith("[error:bad-arg]")


# ── append-file ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_append_file_appends(tmp_path: Path, append_tool):
    f = tmp_path / "log.txt"
    f.write_text("first\n", encoding="utf-8")
    out = await collect(append_tool.tool_run(path=str(f), content="second\n"))
    assert "".join(out).startswith("Appended 7 characters")
    assert f.read_text(encoding="utf-8") == "first\nsecond\n"


@pytest.mark.asyncio
async def test_append_file_missing_file_is_error(tmp_path: Path, append_tool):
    out = await collect(
        append_tool.tool_run(path=str(tmp_path / "nope.txt"), content="x")
    )
    assert out[0].startswith("[error] file not found:")
    # And must NOT create the file silently
    assert not (tmp_path / "nope.txt").exists()


# ── edit-file ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_edit_file_replaces_and_returns_diff(tmp_path: Path, edit_tool):
    f = tmp_path / "code.py"
    f.write_text("a = 1\nb = 2\n", encoding="utf-8")
    out = await collect(
        edit_tool.tool_run(path=str(f), old_string="b = 2", new_string="b = 3")
    )
    text = "".join(out)
    assert text.startswith("Replaced 1 occurrence(s)")
    assert "-b = 2" in text and "+b = 3" in text  # unified diff shown
    assert f.read_text(encoding="utf-8") == "a = 1\nb = 3\n"


@pytest.mark.asyncio
async def test_edit_file_missing_old_string_has_preview(tmp_path: Path, edit_tool):
    f = tmp_path / "code.py"
    f.write_text("alpha\nbeta\n", encoding="utf-8")
    out = await collect(
        edit_tool.tool_run(path=str(f), old_string="gamma", new_string="delta")
    )
    text = "".join(out)
    assert text.startswith("[error] old_string not found")
    assert "alpha" in text  # preview lets the model recover
    assert f.read_text(encoding="utf-8") == "alpha\nbeta\n"  # untouched


@pytest.mark.asyncio
async def test_edit_file_bad_args(edit_tool):
    out = await collect(edit_tool.tool_run(path="", old_string="x", new_string="y"))
    assert out[0].startswith("[error:bad-arg]")
    out = await collect(edit_tool.tool_run(path="f.txt", old_string="", new_string="y"))
    assert out[0].startswith("[error:bad-arg]")


# ── manifest sanity ─────────────────────────────────────────────────


def test_manifests_parse_and_slugs_match():
    """Every new tool ships a manifest whose name slugifies to the
    folder name, with a non-empty parameter schema — otherwise the
    LLM sees the tool but doesn't know how to call it."""
    import json
    import re

    for slug in ("read-file", "write-file", "append-file", "edit-file"):
        mf = json.loads((PACK_ROOT / slug / "manifest.json").read_text("utf-8"))
        assert mf["name"] == slug
        assert mf["description"].strip()
        assert mf["parameters"]["type"] == "object"
        assert mf["parameters"]["properties"]
        slugged = re.sub(r"[^a-z0-9_-]+", "-", mf["name"].strip().lower())
        assert slugged == slug
