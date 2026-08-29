"""Local usage ledger + report-forwarder for the skill market.

Desktop local metrics (skill loads) are already recorded by the
kernel's metrics store as ``kind="skill"``. This module adds a small
file-backed ledger for the events that metrics doesn't cover
(``skill_download`` — a market skill pulled into the local store),
and exposes a ``/report`` endpoint the desktop frontend polls on an
interval (independent of sync), which aggregates the day's numbers and
forwards them to the market service's ``/api/v1/usage``.

Ledger lives at ``<data_dir>/market-usage.json`` (injected via
``market_usage_file`` on ``create_app`` / wired from deploy). Every
entry is ``{day, kind, slug: count}`` — idempotent on the server via
its own dedup key, so re-reporting the same batch is a no-op there.
"""

from __future__ import annotations

import hmac
import json
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("mhc_desktop_backend")

router = APIRouter(prefix="/api/v1/market/usage", tags=["market"])

_VALID = ("skill_download", "skill_enable", "message")


def _ledger_path(request: Request) -> Path | None:
    p = getattr(request.app.state, "market_usage_file", None)
    return Path(p) if p else None


def _load(ledger: Path) -> dict[str, Any]:
    if not ledger.exists():
        return {}
    try:
        return json.loads(ledger.read_text("utf-8"))
    except Exception:  # pragma: no cover
        logger.warning("usage.ledger corrupt %s — reset", ledger)
        return {}


def _save(ledger: Path, data: dict[str, Any]) -> None:
    ledger.parent.mkdir(parents=True, exist_ok=True)
    tmp = ledger.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    tmp.replace(ledger)


async def inc_download(request: Request, slug: str) -> None:
    """Record a local ``skill_download`` for ``slug`` (best-effort)."""
    ledger = _ledger_path(request)
    if ledger is None or not slug:
        return
    import datetime

    day = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")
    try:
        data = _load(ledger)
        key = f"day:{day}:skill_download:{slug}"
        data[key] = data.get(key, 0) + 1
        _save(ledger, data)
    except Exception:  # pragma: no cover
        logger.exception("usage.inc_download failed slug=%s", slug)


def _day() -> str:
    import datetime

    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")


async def _market_request_json(request: Request, path: str, body: dict) -> tuple[bool, str]:
    """Forward a signed request to the market service; return (ok, detail)."""

    import httpx

    base = getattr(request.app.state, "market_base_url", None)
    secret = getattr(request.app.state, "market_secret", None)
    if not base or not secret:
        return False, "market not configured"
    user = getattr(request.state, "user", None)
    end_id = user.username if user is not None else "unknown"
    ts = int(time.time())
    sig = _sign(secret, end_id, ts)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=15.0) as c:
            r = await c.post(
                path,
                json=body,
                headers={"X-MHC-User": end_id, "X-MHC-TS": str(ts), "X-MHC-Sig": sig},
            )
        return r.status_code in (200, 201), f"status={r.status_code}"
    except httpx.HTTPError as e:  # pragma: no cover
        return False, str(e)


def _sign(secret: str, user: str, ts: int) -> str:
    import hashlib

    msg = f"{user}:{ts}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


@router.post("/report")
async def report_usage(request: Request) -> dict[str, Any]:
    """Aggregate the local day's usage and forward to the market service.

    Invocation counts come from the kernel metrics store (skill loads
    are recorded as ``kind="skill"`` there); the ledger supplies
    downloads. The batch is keyed idempotently server-side.
    """

    day = _day()
    events: list[dict[str, Any]] = []

    # skill_invoke: read today's skill loads from the metrics repo.
    metrics = getattr(request.app.state, "metrics_repo", None)
    if metrics is not None:
        try:
            page = await metrics.query_ranking(
                "skills",
                date_from=day,
                date_to=day,
                page=1,
                page_size=200,
            )
            for item in page.items:
                if item.count > 0:
                    events.append({"kind": "skill_invoke", "slug": item.key, "count": item.count})
        except Exception:  # pragma: no cover
            logger.exception("usage.read_metrics failed")

    # ledger events (downloads etc.)
    ledger = _ledger_path(request)
    if ledger is not None:
        data = _load(ledger)
        for key, count in data.items():
            parts = key.split(":", 3)
            if len(parts) != 4 or parts[0] != "day" or parts[1] != day:
                continue
            _, _, kind, slug = parts
            if kind in _VALID and count:
                events.append({"kind": kind, "slug": slug, "count": count})

    # conversations / messages: not tracked here (covered by cloud if needed)
    if not events:
        return {"ok": True, "recorded": 0}

    ok, detail = await _market_request_json(
        request,
        "/api/v1/usage",
        {"end_id": getattr(request.state.user, "username", None) or "kernel", "day": day, "events": events},
    )
    logger.info("usage.report ok=%s events=%s %s", ok, len(events), detail)
    if not ok:
        raise HTTPException(status_code=502, detail=f"market usage report failed: {detail}")
    return {"ok": True, "recorded": len(events)}


# make available for import elsewhere (e.g. add_from_market)
__all__ = ["inc_download", "router"]
