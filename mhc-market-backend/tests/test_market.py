"""Market service tests: publish/list/download, personal space CAS,
HMAC auth. Run: pytest mhc-market-backend/tests/"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mhc_market_backend.app import create_app
from mhc_market_backend.auth import sign

SECRET = "test-secret"


def skill_zip(name: str = "demo-skill", body: str = "hello") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            f"{name}/SKILL.md", f"---\nname: {name}\ndescription: demo\n---\n{body}"
        )
    return buf.getvalue()


def headers(user: str, secret: str = SECRET) -> dict[str, str]:
    ts = int(time.time())
    return {
        "X-MHC-User": user,
        "X-MHC-TS": str(ts),
        "X-MHC-Sig": sign(secret, user, ts),
    }


@pytest.fixture()
def client(tmp_path: Path):
    app = create_app(data_root=tmp_path, secret=SECRET)
    return TestClient(app)


def test_health_no_auth(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200


def test_publish_list_download_roundtrip(client):
    blob = skill_zip()
    r = client.put(
        "/api/v1/skills/demo-skill",
        json={
            "data": base64.b64encode(blob).decode(),
            "sha": "a" * 64,
            "display_name": "Demo Skill",
            "category": "coding",
        },
        headers=headers("alice"),
    )
    assert r.status_code == 200, r.text
    key = r.json()["slug"]
    assert key.startswith("demo-skill-")  # {base}-{random6}

    r = client.get("/api/v1/skills?q=demo")
    assert r.status_code == 200 and len(r.json()) == 1

    r = client.get(f"/api/v1/skills/{key}/download")
    assert r.status_code == 200
    assert r.headers["X-Content-Sha"] == "a" * 64
    # downloads counter bumped
    assert client.get(f"/api/v1/skills/{key}").json()["downloads"] == 1


def test_publish_random_key_and_reuse(client):
    """Key = {base}-{random6}. Same author + same display name reuses
    the key (re-publish overwrites); different authors get distinct
    keys, so same-named skills coexist."""
    blob = base64.b64encode(skill_zip()).decode()
    r = client.put(
        "/api/v1/skills/x", json={"data": blob, "sha": "a", "display_name": "x"}, headers=headers("alice")
    )
    assert r.status_code == 200
    k1 = r.json()["slug"]
    assert k1.startswith("x-") and k1 != "x"
    # same author + same name -> same key, overwrite
    r = client.put(
        "/api/v1/skills/x", json={"data": blob, "sha": "b", "display_name": "x"}, headers=headers("alice")
    )
    assert r.status_code == 200 and r.json()["slug"] == k1
    # different author, same name -> own key, coexist
    r = client.put(
        "/api/v1/skills/x", json={"data": blob, "sha": "c", "display_name": "x"}, headers=headers("bob")
    )
    assert r.status_code == 200
    k2 = r.json()["slug"]
    assert k2 != k1 and k2.startswith("x-")
    assert len(client.get("/api/v1/skills").json()) == 2


def test_publish_rejects_identical_content(client):
    """Exact-copy publishes are rejected: identical content (same sha)
    may only exist once."""
    blob = base64.b64encode(skill_zip()).decode()
    r = client.put(
        "/api/v1/skills/dup", json={"data": blob, "sha": "s" * 64, "display_name": "Dup"},
        headers=headers("alice"),
    )
    assert r.status_code == 200
    key = r.json()["slug"]
    # same author, same sha -> idempotent, same key
    r = client.put(
        "/api/v1/skills/dup", json={"data": blob, "sha": "s" * 64, "display_name": "Dup"},
        headers=headers("alice"),
    )
    assert r.status_code == 200 and r.json()["slug"] == key
    # different author, same sha -> 409
    r = client.put(
        "/api/v1/skills/dup", json={"data": blob, "sha": "s" * 64, "display_name": "Dup"},
        headers=headers("bob"),
    )
    assert r.status_code == 409


def test_publish_rejects_bad_input(client):
    r = client.put(
        "/api/v1/skills/UPPER",
        json={"data": base64.b64encode(skill_zip()).decode(), "sha": "a"},
        headers=headers("alice"),
    )
    assert r.status_code == 400
    # zip without SKILL.md
    r = client.put(
        "/api/v1/skills/x",
        json={"data": base64.b64encode(b"not a zip").decode(), "sha": "a"},
        headers=headers("alice"),
    )
    assert r.status_code == 400


def test_publish_display_name_from_md(client):
    """市场展示名一律来自 SKILL.md 的 name，忽略调用方传入的花名 —
    保证市场展示与 MD 文件一致。"""
    blob = base64.b64encode(skill_zip(name="real-name", body="v1")).decode()
    r = client.put(
        "/api/v1/skills/real-name",
        json={
            "data": blob,
            "sha": "n" * 64,
            "display_name": "Pretty Market Name",
            "category": "coding",
        },
        headers=headers("alice"),
    )
    assert r.status_code == 200, r.text
    key = r.json()["slug"]
    # 花名被 MD name 覆盖
    assert r.json()["display_name"] == "real-name"
    # 列表同样
    r = client.get("/api/v1/skills")
    assert r.json()[0]["display_name"] == "real-name"
    assert key.startswith("real-name-")


def test_delist_author_only_and_hides_public(client):
    """Delist removes the skill from every public read path but keeps
    the row; re-publish by the author resurrects it (same key)."""
    blob = base64.b64encode(skill_zip()).decode()
    r = client.put(
        "/api/v1/skills/dskill",
        json={"data": blob, "sha": "d" * 64, "display_name": "D Skill"},
        headers=headers("alice"),
    )
    assert r.status_code == 200
    key = r.json()["slug"]

    # only the author can delist
    assert client.delete(f"/api/v1/skills/{key}", headers=headers("bob")).status_code == 403

    r = client.delete(f"/api/v1/skills/{key}", headers=headers("alice"))
    assert r.status_code == 204

    # gone from the public market everywhere
    assert client.get("/api/v1/skills").json() == []
    assert client.get(f"/api/v1/skills/{key}").status_code == 404
    assert client.get(f"/api/v1/skills/{key}/files").status_code == 404
    assert client.get(f"/api/v1/skills/{key}/download").status_code == 404
    assert client.get(f"/api/v1/skills/{key}/rating").status_code == 404
    assert client.get(f"/api/v1/skills/{key}/reviews").status_code == 404

    # author re-publishes → resurrected, same key, visible again
    r = client.put(
        "/api/v1/skills/dskill",
        json={"data": blob, "sha": "d" * 64, "display_name": "D Skill"},
        headers=headers("alice"),
    )
    assert r.status_code == 200 and r.json()["slug"] == key
    assert client.get(f"/api/v1/skills/{key}").status_code == 200
    assert len(client.get("/api/v1/skills").json()) == 1


def test_init_reconciles_stale_display_names(tmp_path: Path):
    """启动时对齐存量 display_name 与 MD name（旧种子花名 → MD 名）。"""
    import sqlite3 as _sql

    from mhc_market_backend.store import MarketStore

    store = MarketStore(tmp_path)
    blob = skill_zip(name="stale-name", body="v1")
    r = store.publish(
        slug="stale-name",
        user="alice",
        zip_bytes=blob,
        sha="s" * 64,
        display_name="Stale Pretty Name",
        category="other",
    )
    assert r["display_name"] == "stale-name"  # 新逻辑直接纠正
    # 手动把 DB 改回旧花名，模拟历史数据
    con = _sql.connect(store._db)
    con.execute("UPDATE skills SET display_name='Stale Pretty Name' WHERE slug=?", (r["slug"],))
    con.commit()
    con.close()
    # 重新初始化 → 对齐
    store2 = MarketStore(tmp_path)
    assert store2.get_public(r["slug"])["display_name"] == "stale-name"


def test_delist_keeps_personal_space_copies_flagged(client):
    """After a delist, previously-added copies stay in personal spaces
    (meta preserved) but are flagged delisted via content-sha match,
    even when the cloud copy slug differs from the market key."""
    blob = base64.b64encode(skill_zip(name="copied", body="v1")).decode()
    r = client.put(
        "/api/v1/skills/copy-src",
        json={"data": blob, "sha": "c" * 64, "display_name": "Copy Me"},
        headers=headers("alice"),
    )
    assert r.status_code == 200
    key = r.json()["slug"]

    # bob adds it — cloud copy under a DIFFERENT slug (the desktop add
    # flow keys the backup by the local slug, not the market key)
    r = client.put(
        "/api/v1/me/skills/copied",
        json={"data": blob, "sha": "c" * 64},
        headers=headers("bob"),
    )
    assert r.status_code == 200

    # alice delists
    assert client.delete(f"/api/v1/skills/{key}", headers=headers("alice")).status_code == 204

    # bob's personal space keeps the copy, flagged, with real meta
    mine = client.get("/api/v1/me/skills", headers=headers("bob")).json()
    assert [i["slug"] for i in mine] == ["copied"]
    assert mine[0]["delisted"] == 1
    assert mine[0]["display_name"] == "copied"
    assert mine[0]["author"] == "alice"
    # the copy itself still works (download + delete)
    assert client.get("/api/v1/me/skills/copied", headers=headers("bob")).status_code == 200

    # author re-publishes → the copy's delisted flag clears
    r = client.put(
        "/api/v1/skills/copy-src",
        json={"data": blob, "sha": "c" * 64, "display_name": "Copy Me"},
        headers=headers("alice"),
    )
    assert r.status_code == 200
    mine = client.get("/api/v1/me/skills", headers=headers("bob")).json()
    assert mine[0]["delisted"] == 0

    # the copy can still be removed from the personal space
    assert client.delete("/api/v1/me/skills/copied", headers=headers("bob")).status_code == 204
    assert client.get("/api/v1/me/skills", headers=headers("bob")).json() == []


def test_delist_edited_copy_not_flagged(client):
    """A user who edited their copy diverged from the market entry:
    the delisted flag only follows content identity."""
    blob_a = base64.b64encode(skill_zip(name="ed", body="orig")).decode()
    r = client.put(
        "/api/v1/skills/ed-src",
        json={"data": blob_a, "sha": "e" * 64, "display_name": "Ed"},
        headers=headers("alice"),
    )
    assert r.status_code == 200
    key = r.json()["slug"]
    client.put(
        "/api/v1/me/skills/ed",
        json={"data": blob_a, "sha": "e" * 64},
        headers=headers("bob"),
    )
    # bob edits the cloud copy (content sha diverges)
    blob_b = base64.b64encode(skill_zip(name="ed", body="forked")).decode()
    client.put(
        "/api/v1/me/skills/ed",
        json={"data": blob_b, "sha": "e2" * 32},
        headers=headers("bob"),
    )
    # alice delists the original
    client.delete(f"/api/v1/skills/{key}", headers=headers("alice"))
    mine = client.get("/api/v1/me/skills", headers=headers("bob")).json()
    assert mine[0]["delisted"] == 0  # bob's fork is his own



def test_personal_space_cas(client):
    blob1, blob2 = skill_zip(body="v1"), skill_zip(body="v2")
    b1 = base64.b64encode(blob1).decode()
    b2 = base64.b64encode(blob2).decode()
    h = headers("alice")

    r = client.put("/api/v1/me/skills/demo", json={"data": b1, "sha": "s1"}, headers=h)
    assert r.status_code == 200

    # CAS with stale base_sha → 409
    r = client.put(
        "/api/v1/me/skills/demo", json={"data": b2, "sha": "s2", "base_sha": "wrong"}, headers=h
    )
    assert r.status_code == 409

    # CAS with correct base → overwrite
    r = client.put(
        "/api/v1/me/skills/demo", json={"data": b2, "sha": "s2", "base_sha": "s1"}, headers=h
    )
    assert r.status_code == 200

    r = client.get("/api/v1/me/skills", headers=h)
    assert [i["slug"] for i in r.json()] == ["demo"]
    r = client.get("/api/v1/me/skills/demo", headers=h)
    assert r.headers["X-Content-Sha"] == "s2"


def test_personal_space_delete(client):
    h = headers("alice")
    blob = base64.b64encode(skill_zip()).decode()
    client.put("/api/v1/me/skills/d", json={"data": blob, "sha": "s"}, headers=h)
    assert client.delete("/api/v1/me/skills/d", headers=h).status_code == 204
    assert client.get("/api/v1/me/skills/d", headers=h).status_code == 404


def test_hmac_rejects(client):
    blob = base64.b64encode(skill_zip()).decode()
    # missing headers
    assert client.put("/api/v1/me/skills/d", json={"data": blob}).status_code == 401
    # bad signature
    r = client.put(
        "/api/v1/me/skills/d", json={"data": blob}, headers=headers("alice", "wrong-secret")
    )
    assert r.status_code == 401
    # stale timestamp
    ts = int(time.time()) - 10_000
    h = {
        "X-MHC-User": "alice",
        "X-MHC-TS": str(ts),
        "X-MHC-Sig": hmac.new(
            SECRET.encode(), f"alice:{ts}".encode(), hashlib.sha256
        ).hexdigest(),
    }
    assert client.put("/api/v1/me/skills/d", json={"data": blob}, headers=h).status_code == 401


def test_stories_crud(client):
    r = client.post(
        "/api/v1/stories",
        json={"title": "我的使用心得", "skill_slug": "demo", "content": "# 标题\n正文"},
        headers=headers("alice"),
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    assert r.json()["author"] == "alice"

    # anonymous read
    assert client.get("/api/v1/stories").json()[0]["id"] == sid
    assert client.get(f"/api/v1/stories/{sid}").json()["title"] == "我的使用心得"
    assert client.get("/api/v1/stories/nope").status_code == 404

    # empty title rejected
    r = client.post(
        "/api/v1/stories", json={"title": "", "content": "x"}, headers=headers("bob")
    )
    assert r.status_code == 400


def test_web_login_and_bearer(client):
    """The standalone web app logs in with the demo accounts and uses
    a Bearer token — no HMAC headers needed."""
    r = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "wonderland"}
    )
    assert r.status_code == 200
    token = r.json()["token"]
    h = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/v1/me/skills", headers=h).status_code == 200
    # bad password
    r = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "nope"}
    )
    assert r.status_code == 401
    # bad token
    r = client.get("/api/v1/me/skills", headers={"Authorization": "Bearer junk"})
    assert r.status_code == 401


def test_web_upload_sha_matches_kernel_algorithm(client):
    """Web uploads omit sha — the server computes it the same way the
    kernel's content_sha does (relpath + \\0 + bytes + \\0, sorted)."""
    import hashlib

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("web-skill/SKILL.md", "---\nname: web-skill\ndescription: d\n---\nbody")
        zf.writestr("web-skill/ref/a.md", "ref content")
    blob = buf.getvalue()

    r = client.post(
        "/api/v1/auth/login", json={"username": "bob", "password": "builder"}
    )
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    resp = client.put(
        "/api/v1/me/skills/web-skill",
        json={"data": base64.b64encode(blob).decode(), "sha": ""},
        headers=h,
    )
    assert resp.status_code == 200, resp.text
    server_sha = resp.json()["sha"]

    # kernel algorithm
    ks = hashlib.sha256()
    for rel, data in (("SKILL.md", b"---\nname: web-skill\ndescription: d\n---\nbody"), ("ref/a.md", b"ref content")):
        ks.update(rel.encode())
        ks.update(b"\0")
        ks.update(data)
        ks.update(b"\0")
    assert server_sha == ks.hexdigest()


def test_boot_requires_secret(tmp_path: Path):
    import os

    os.environ.pop("MHC_MARKET_SECRET", None)
    with pytest.raises(RuntimeError):
        create_app(data_root=tmp_path, secret="")


# ── capability additions: admin / pagination / full-text / ratings / token ──


@pytest.fixture()
def admin_client(tmp_path: Path):
    app = create_app(data_root=tmp_path / "m", secret=SECRET, admin_token="adm")
    return TestClient(app)


def test_admin_featured_gated(admin_client):
    c = admin_client
    blob = base64.b64encode(skill_zip("fs")).decode()
    r = c.put(
        "/api/v1/skills/fs",
        json={"data": blob, "sha": "a", "display_name": "Fs"},
        headers=headers("alice"),
    )
    sk = r.json()["slug"]
    # wrong admin token → 403
    r = c.post(
        f"/api/v1/admin/skills/{sk}/featured",
        json={"featured": True},
        headers={"X-MHC-Admin": "nope"},
    )
    assert r.status_code == 403
    # correct token toggles featured
    r = c.post(
        f"/api/v1/admin/skills/{sk}/featured",
        json={"featured": True},
        headers={"X-MHC-Admin": "adm"},
    )
    assert r.status_code == 200 and r.json()["featured"] == 1
    assert len(c.get("/api/v1/skills?featured=true").json()) == 1


def test_admin_requires_config(client):
    # default app has no admin_token → admin endpoints 403
    assert client.get("/api/v1/admin/skills").status_code == 403


def test_pagination(client):
    for i in range(3):
        b = base64.b64encode(skill_zip(f"s{i}", body=f"v{i}")).decode()
        client.put(
            f"/api/v1/skills/s{i}",
            json={"data": b, "sha": f"a{i}", "display_name": f"S{i}"},
            headers=headers("alice"),
        )
    r = client.get("/api/v1/skills?limit=1")
    assert len(r.json()) == 1
    assert r.headers["X-Total-Count"] == "3"
    r = client.get("/api/v1/skills?limit=2&offset=2")
    assert len(r.json()) == 1


def test_full_text_search(client):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "search-me/SKILL.md",
            "---\nname: search-me\ndescription: d\n---\nuniquezzz body word",
        )
    blob = base64.b64encode(buf.getvalue()).decode()
    client.put(
        "/api/v1/skills/search-me",
        json={"data": blob, "sha": "a", "display_name": "Search"},
        headers=headers("alice"),
    )
    # the term only appears in the SKILL.md body, matched via FTS
    assert len(client.get("/api/v1/skills?q=uniquezzz").json()) == 1


def test_token_expires(tmp_path: Path, monkeypatch):
    from mhc_market_backend import accounts

    monkeypatch.setattr(accounts, "TOKEN_TTL", -1)
    app = create_app(data_root=tmp_path, secret=SECRET)
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", json={"username": "alice", "password": "wonderland"})
    token = r.json()["token"]
    assert (
        c.get("/api/v1/me/skills", headers={"Authorization": f"Bearer {token}"}).status_code
        == 401
    )


def test_ops_stats(admin_client):
    c = admin_client
    blob = base64.b64encode(skill_zip("st")).decode()
    c.put(
        "/api/v1/skills/st",
        json={"data": blob, "sha": "a", "display_name": "St"},
        headers=headers("alice"),
    )
    s = c.get("/api/v1/admin/stats", headers={"X-MHC-Admin": "adm"}).json()
    assert s["public_skills"] >= 1
    d = c.get("/api/v1/admin/diagnostics", headers={"X-MHC-Admin": "adm"}).json()
    assert d["ok"] is True
    logs = c.get("/api/v1/admin/logs", headers={"X-MHC-Admin": "adm"})
    assert logs.status_code == 200 and isinstance(logs.json()["lines"], list)


def test_ops_backup_restore(admin_client):
    c = admin_client
    blob = base64.b64encode(skill_zip("bk")).decode()
    r = c.put(
        "/api/v1/skills/bk",
        json={"data": blob, "sha": "a", "display_name": "Bk"},
        headers=headers("alice"),
    )
    key = r.json()["slug"]
    r = c.post("/api/v1/admin/backup", headers={"X-MHC-Admin": "adm"})
    assert r.status_code == 200
    name = r.json()["backup"]
    assert any(
        b["name"] == name
        for b in c.get("/api/v1/admin/backups", headers={"X-MHC-Admin": "adm"}).json()
    )
    # mutate then restore
    c.put(
        "/api/v1/skills/bk",
        json={"data": base64.b64encode(skill_zip("bk", "v2")).decode(), "sha": "b", "display_name": "Bk"},
        headers=headers("alice"),
    )
    assert c.get(f"/api/v1/skills/{key}").json()["display_name"] == "bk"
    rr = c.post(f"/api/v1/admin/backups/{name}/restore", headers={"X-MHC-Admin": "adm"})
    assert rr.status_code == 200
    assert c.get(f"/api/v1/skills/{key}").json()["display_name"] == "bk"
    # path traversal: routed away (405) or store-level guarded (400)
    assert (
        c.post("/api/v1/admin/backups/..%2F..%2F..%2Fetc%2Fpasswd/restore", headers={"X-MHC-Admin": "adm"}).status_code
        in (400, 404, 405, 422)
    )
    # nonexistent bare name → 404 at store level
    assert (
        c.post("/api/v1/admin/backups/nope.db/restore", headers={"X-MHC-Admin": "adm"}).status_code
        == 404
    )


def test_reviews_upsert_and_avg(client):
    blob = base64.b64encode(skill_zip("rv")).decode()
    r = client.put(
        "/api/v1/skills/rv",
        json={"data": blob, "sha": "a", "display_name": "Rv"},
        headers=headers("alice"),
    )
    rv = r.json()["slug"]
    r = client.post(
        f"/api/v1/skills/{rv}/reviews",
        json={"rating": 5, "comment": "great"},
        headers=headers("alice"),
    )
    assert r.status_code == 201 and r.json()["average"] == 5.0 and r.json()["count"] == 1
    # same user re-rates (upsert)
    client.post(f"/api/v1/skills/{rv}/reviews", json={"rating": 3}, headers=headers("alice"))
    assert len(client.get(f"/api/v1/skills/{rv}/reviews").json()) == 1
    # second user
    client.post(f"/api/v1/skills/{rv}/reviews", json={"rating": 1}, headers=headers("bob"))
    r = client.get(f"/api/v1/skills/{rv}/rating")
    assert r.json()["average"] == 2.0 and r.json()["count"] == 2
    # rating required
    assert (
        client.post(
            "/api/v1/skills/rv/reviews", json={"comment": "x"}, headers=headers("demo")
        ).status_code
        == 400
    )
