"""Tests for session CRUD bulk endpoints: ``delete-many`` and ``clear``."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from mhc_desktop_backend.api.sessions import get_store as sessions_get_store
from mhc_desktop_backend.api.sessions import router as sessions_router
from mhc_desktop_deploy.impls.file_stores.session_store import SessionStore


@pytest.fixture
def store(tmp_path):
    return SessionStore(tmp_path / "sessions.json")


@pytest.fixture
def client(store):
    app = FastAPI()
    app.include_router(sessions_router)

    async def _override():
        return store

    app.dependency_overrides[sessions_get_store] = _override
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_delete_many_removes_listed(client, store):
    ids = []
    for i in range(3):
        r = await client.post("/api/v1/sessions", json={"title": f"s{i}"})
        ids.append(r.json()["id"])
    survivor = (await client.post("/api/v1/sessions", json={"title": "keep"})).json()[
        "id"
    ]

    r = await client.post("/api/v1/sessions/delete-many", json={"ids": ids[:2]})
    assert r.status_code == 200, r.text
    assert r.json() == {"removed": 2}

    remaining = (await client.get("/api/v1/sessions")).json()
    remaining_ids = {s["id"] for s in remaining}
    assert ids[2] in remaining_ids
    assert survivor in remaining_ids
    assert ids[0] not in remaining_ids
    assert ids[1] not in remaining_ids


@pytest.mark.asyncio
async def test_delete_many_deduplicates(client):
    ids = []
    for _ in range(2):
        ids.append((await client.post("/api/v1/sessions", json={})).json()["id"])
    # Same id twice + an unknown id; only the unique real one is removed.
    r = await client.post(
        "/api/v1/sessions/delete-many", json={"ids": [ids[0], ids[0], "nope"]}
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"removed": 1}


@pytest.mark.asyncio
async def test_delete_many_rejects_bad_payload(client):
    r = await client.post("/api/v1/sessions/delete-many", json={"ids": "nope"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_clear_wipes_everything(client):
    for i in range(4):
        await client.post("/api/v1/sessions", json={"title": f"s{i}"})
    r = await client.post("/api/v1/sessions/clear")
    assert r.status_code == 200, r.text
    assert r.json() == {"removed": 4}
    remaining = (await client.get("/api/v1/sessions")).json()
    assert remaining == []
