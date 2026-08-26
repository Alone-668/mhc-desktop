"""Session roundtrip with per-message skills metadata.

Skills attached to a user message are stored on that message's dict
under the ``skills`` key. They survive a JSON write/read cycle so the
controller can read them back when iterating inside an agent run,
and the frontend can show which skills were in scope when the reply
was generated.
"""

from __future__ import annotations

import asyncio

import pytest

from mhc_desktop_deploy.impls.file_stores.session_store import SessionStore


@pytest.fixture
def store(tmp_path):
    return SessionStore(sessions_dir=tmp_path / "s")


def test_session_roundtrip_preserves_user_message_skills(store):
    async def main():
        sess = await store.create({"title": "roundtrip"})
        await store.update(
            sess.id,
            {
                "messages": [
                    {
                        "role": "user",
                        "content": "summarize this",
                        "skills": ["summarize", "code-review"],
                    },
                    {"role": "assistant", "content": "### TL;DR ..."},
                    {"role": "user", "content": "what is 2+2"},
                ]
            },
        )
        sess = await store.get(sess.id)
        assert sess is not None
        msgs = sess.messages
        # User message 1: skills list preserved verbatim, in order
        assert msgs[0]["skills"] == ["summarize", "code-review"]
        # Assistant message: no skills field
        assert "skills" not in msgs[1]
        # User message 2: no skills attached (empty / missing)
        assert "skills" not in msgs[2] or msgs[2].get("skills") in (None, [])

    asyncio.run(main())


def test_session_skills_metadata_serializes_through_disk(store):
    """Write the session to disk and re-read it \u2014 the JSON file is
    what other processes see, so we must round-trip through it."""

    async def main():
        sess = await store.create({})
        await store.update(
            sess.id,
            {
                "messages": [
                    {"role": "user", "content": "hi", "skills": ["a", "b"]},
                ]
            },
        )
        # Read the raw JSON file on disk to make sure it's there.
        path = store._session_path(sess.id)
        import json

        raw = json.loads(path.read_text("utf-8"))
        assert raw["messages"][0]["skills"] == ["a", "b"]
        # Reload via store.
        sess2 = await store.get(sess.id)
        assert sess2 is not None
        assert sess2.messages[0]["skills"] == ["a", "b"]

    asyncio.run(main())
