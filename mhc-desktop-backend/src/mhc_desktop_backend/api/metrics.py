"""Usage-metrics dashboard API.

Three endpoints:

* ``GET /api/v1/metrics/summary`` — top cards (totals + today).
* ``GET /api/v1/metrics/ranking`` — server-side paginated full
  list (tools / skills / mcps / models).
* ``GET /api/v1/metrics/trend`` — daily time series for charts.

The summary / trend endpoints merge conversation counts (from the
session store) with the metrics repo's LLM / tool aggregates — the
session is the source of truth for "did a conversation happen
today?", independent of whether the LLM was reached. This avoids
double-counting in the chat handler and keeps the conversation
metric decoupled from "did the LLM stream finish?".

Pagination is pushed down to the backend — ``query_ranking``
applies the slice itself, so external adapters can ``LIMIT``/``OFFSET``
on indexed columns and never materialise the full ranking.

The dashboard is a local-only feature today (single user), so
there is no auth layer here — matches the rest of the backend's
local API. Adding multi-user auth would mean the same surface
under a permission guard, identical to the gateway's metrics
management endpoints.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from mhc_desktop_backend.metrics.protocols import (
    RANKING_KINDS,
    MetricsRepositoryProtocol,
)
from mhc_desktop_backend.protocols import SessionStoreProtocol

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])


def _repo(request: Request) -> MetricsRepositoryProtocol:
    repo = getattr(request.app.state, "metrics_repo", None)
    if repo is None:
        raise HTTPException(503, "metrics repository not configured")
    return repo


def _session_store(request: Request) -> SessionStoreProtocol | None:
    return getattr(request.app.state, "session_store", None)


def _parse_date(value: str | None, name: str) -> str | None:
    if not value:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(422, f"Invalid {name}: expected YYYY-MM-DD")
    return value


def _checked_dates(
    date_from: str | None, date_to: str | None
) -> tuple[str | None, str | None]:
    d_from = _parse_date(date_from, "date_from")
    d_to = _parse_date(date_to, "date_to")
    if d_from and d_to and d_from > d_to:
        raise HTTPException(422, "date_from must be <= date_to")
    return d_from, d_to


async def _conv_counts(
    session_store: SessionStoreProtocol | None,
    date_from: str | None,
    date_to: str | None,
) -> dict[str, int]:
    """Pull per-day session counts from the session store.

    Falls back to empty on missing store — the metrics endpoint
    still works, it just won't surface the conversation counter.
    """
    if session_store is None:
        return {}
    try:
        return await session_store.count_by_day(date_from, date_to)
    except Exception:  # pragma: no cover — defensive
        return {}


@router.get("/summary")
async def get_metrics_summary(
    request: Request,
    date_from: str | None = Query(
        None, description="Start date (inclusive, YYYY-MM-DD)"
    ),
    date_to: str | None = Query(None, description="End date (inclusive, YYYY-MM-DD)"),
) -> dict[str, Any]:
    repo = _repo(request)
    d_from, d_to = _checked_dates(date_from, date_to)
    conv = await _conv_counts(_session_store(request), d_from, d_to)
    summary = await repo.query_summary(
        date_from=d_from,
        date_to=d_to,
        conversation_count_by_day=conv,
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "date_from": d_from,
        "date_to": d_to,
        **summary.to_dict(),
    }


@router.get("/ranking")
async def get_metrics_ranking(
    request: Request,
    kind: str = Query(..., description="tools|skills|mcps|models"),
    page: int = Query(1, ge=1, description="1-based page number"),
    page_size: int = Query(10, ge=1, le=100, description="Items per page"),
    date_from: str | None = Query(
        None, description="Start date (inclusive, YYYY-MM-DD)"
    ),
    date_to: str | None = Query(None, description="End date (inclusive, YYYY-MM-DD)"),
) -> dict[str, Any]:
    if kind not in RANKING_KINDS:
        raise HTTPException(
            422,
            f"Invalid kind: expected one of {', '.join(RANKING_KINDS)}",
        )
    repo = _repo(request)
    d_from, d_to = _checked_dates(date_from, date_to)
    res = await repo.query_ranking(
        kind=kind,
        date_from=d_from,
        date_to=d_to,
        page=page,
        page_size=page_size,
    )
    return {
        "kind": kind,
        "items": [i.to_dict() for i in res.items],
        "total": res.total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/trend")
async def get_metrics_trend(
    request: Request,
    date_from: str | None = Query(
        None, description="Start date (inclusive, YYYY-MM-DD)"
    ),
    date_to: str | None = Query(None, description="End date (inclusive, YYYY-MM-DD)"),
) -> dict[str, Any]:
    repo = _repo(request)
    d_from, d_to = _checked_dates(date_from, date_to)
    conv = await _conv_counts(_session_store(request), d_from, d_to)
    points = await repo.query_trend(
        date_from=d_from,
        date_to=d_to,
        conversation_count_by_day=conv,
    )
    return {
        "date_from": d_from,
        "date_to": d_to,
        "points": [p.to_dict() for p in points],
    }


__all__ = ["router"]
