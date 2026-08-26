"""User preferences store + API contract tests.

The prefs store is the simplest subsystem in the backend on purpose:
one file, one field exposed today, async lock for concurrent writes.
The tests here pin:

* the GET/PUT API shape (whitelist, validation, persistence)
* the ``update`` partial-merge semantics (None means untouched)
* the file-backed store's behaviour on missing/corrupt files
* unknown keys round-trip through ``extra`` so server-side schema
  upgrades don't drop user data
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mhc_desktop_backend.app import create_app
from mhc_desktop_deploy.impls.file_stores.prefs_store import PrefsStore


@pytest.fixture
def tmp_prefs_file(tmp_path: Path) -> Path:
    return tmp_path / "prefs.json"


# ── PrefsStore unit tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_store_get_returns_defaults_when_file_missing(tmp_path: Path) -> None:
    store = PrefsStore(prefs_file=tmp_path / "prefs.json")
    prefs = await store.get()
    assert prefs.system_prompt_addition == ""
    assert prefs.updated_at == ""
    assert prefs.extra == {}


@pytest.mark.asyncio
async def test_store_update_writes_file_and_round_trips(tmp_path: Path) -> None:
    p = tmp_path / "prefs.json"
    store = PrefsStore(prefs_file=p)
    prefs = await store.update(system_prompt_addition="always reply in 中文")
    assert prefs.system_prompt_addition == "always reply in 中文"
    assert prefs.updated_at  # ISO timestamp
    on_disk = json.loads(p.read_text("utf-8"))
    assert on_disk["system_prompt_addition"] == "always reply in 中文"
    # Empty extra must NOT be written — keeps the file minimal.
    assert "extra" not in on_disk


@pytest.mark.asyncio
async def test_store_update_strips_whitespace(tmp_path: Path) -> None:
    store = PrefsStore(prefs_file=tmp_path / "prefs.json")
    prefs = await store.update(system_prompt_addition="  be concise  \n")
    assert prefs.system_prompt_addition == "be concise"


@pytest.mark.asyncio
async def test_store_update_none_means_untouched(tmp_path: Path) -> None:
    p = tmp_path / "prefs.json"
    store = PrefsStore(prefs_file=p)
    await store.update(system_prompt_addition="first draft")
    # ``None`` in the second call must leave the field alone.
    again = await store.update(system_prompt_addition=None)
    assert again.system_prompt_addition == "first draft"


@pytest.mark.asyncio
async def test_store_update_can_clear_with_empty_string(tmp_path: Path) -> None:
    """Empty string is a *value* (the user cleared their addition).

    We must distinguish ``None`` (untouched) from ``""`` (clear). The
    contract is: empty string sets the field to "". A previous test
    already covered that ``None`` is a no-op.
    """
    store = PrefsStore(prefs_file=tmp_path / "prefs.json")
    await store.update(system_prompt_addition="something")
    cleared = await store.update(system_prompt_addition="")
    assert cleared.system_prompt_addition == ""


@pytest.mark.asyncio
async def test_store_handles_corrupt_file(tmp_path: Path) -> None:
    """A broken prefs.json must not brick the app: get() falls back
    to defaults so the user can save over it. Without this, a power
    loss mid-write would prevent every chat request.
    """
    p = tmp_path / "prefs.json"
    p.write_text("{not valid json", encoding="utf-8")
    store = PrefsStore(prefs_file=p)
    prefs = await store.get()
    assert prefs.system_prompt_addition == ""
    # And a follow-up save must overwrite the broken file cleanly.
    await store.update(system_prompt_addition="recovered")
    assert json.loads(p.read_text("utf-8"))["system_prompt_addition"] == "recovered"


@pytest.mark.asyncio
async def test_store_preserves_unknown_keys(tmp_path: Path) -> None:
    """Forward compat: an older client may write a key the server
    hasn't learned yet. The store must round-trip it so the user's
    settings survive a server-side schema upgrade.
    """
    p = tmp_path / "prefs.json"
    p.write_text(
        json.dumps(
            {"system_prompt_addition": "x", "future_key": {"nested": True}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = PrefsStore(prefs_file=p)
    prefs = await store.get()
    assert prefs.extra.get("future_key") == {"nested": True}
    # Update must keep the unknown key around.
    await store.update(system_prompt_addition="y")
    on_disk = json.loads(p.read_text("utf-8"))
    assert on_disk["system_prompt_addition"] == "y"
    # Unknown keys round-trip through ``extra`` so the schema is the
    # single source of truth for which top-level fields the server
    # recognises; future server additions read them back out of ``extra``.
    assert on_disk["extra"]["future_key"] == {"nested": True}


# ── HTTP API tests ───────────────────────────────────────────────────────────


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Build an app wired with a tmp prefs file."""
    p = tmp_path / "prefs.json"
    store = PrefsStore(prefs_file=p)
    app = create_app(prefs=store)
    return TestClient(app)


def test_get_prefs_default_when_no_file(client: TestClient) -> None:
    r = client.get("/api/v1/prefs")
    assert r.status_code == 200
    assert r.json() == {"system_prompt_addition": "", "updated_at": ""}


def test_put_prefs_round_trips(client: TestClient) -> None:
    r = client.put(
        "/api/v1/prefs",
        json={"system_prompt_addition": "be concise; prefer 中文"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["system_prompt_addition"] == "be concise; prefer 中文"
    assert body["updated_at"]

    r = client.get("/api/v1/prefs")
    assert r.json()["system_prompt_addition"] == "be concise; prefer 中文"


def test_put_prefs_rejects_non_string(client: TestClient) -> None:
    r = client.put(
        "/api/v1/prefs",
        json={"system_prompt_addition": ["not", "a", "string"]},
    )
    assert r.status_code == 400


def test_put_prefs_rejects_oversized(client: TestClient) -> None:
    """8 KiB cap protects the per-request cost; the system prompt
    is sent every chat turn, so a runaway 1MB string would balloon
    tokens across every call.
    """
    r = client.put(
        "/api/v1/prefs",
        json={"system_prompt_addition": "a" * (8 * 1024 + 1)},
    )
    assert r.status_code == 400


def test_put_prefs_empty_body_is_400(client: TestClient) -> None:
    r = client.put("/api/v1/prefs", json={})
    assert r.status_code == 400


def test_put_prefs_ignores_unknown_fields(client: TestClient) -> None:
    """A newer client may send fields the server hasn't learned yet.
    We must NOT 400 on that — silently drop the unknown keys so the
    user's PUT succeeds.
    """
    r = client.put(
        "/api/v1/prefs",
        json={"system_prompt_addition": "ok", "future_thing": True},
    )
    assert r.status_code == 200
    assert r.json()["system_prompt_addition"] == "ok"


def test_put_prefs_can_clear(client: TestClient) -> None:
    client.put("/api/v1/prefs", json={"system_prompt_addition": "x"})
    r = client.put("/api/v1/prefs", json={"system_prompt_addition": ""})
    assert r.status_code == 200
    assert r.json()["system_prompt_addition"] == ""
