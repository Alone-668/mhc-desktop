"""User preferences HTTP API.

Single endpoint pair under ``/api/v1/prefs``:

* ``GET  /``  return current prefs (always safe — no secrets here)
* ``PUT  /``  partial update; only whitelisted fields accepted

The store is intentionally tiny (just ``system_prompt_addition`` today)
but the route is shaped to grow: PUT takes a partial body and only
persists fields it knows about, ignoring the rest so the client can
forwards-compatibly include keys the server hasn't learned yet.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from mhc_desktop_backend.protocols import PrefsStoreProtocol

logger = logging.getLogger("mhc_desktop_backend")

router = APIRouter(prefix="/api/v1/prefs", tags=["prefs"])


def get_store(request: Request) -> PrefsStoreProtocol:
    store: PrefsStoreProtocol | None = getattr(request.app.state, "prefs_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="prefs store not initialized")
    return store


@router.get("")
async def get_prefs(store: PrefsStoreProtocol = Depends(get_store)) -> dict[str, Any]:
    prefs = await store.get()
    return prefs.to_dict()


@router.put("")
async def update_prefs(
    body: dict[str, Any] = Body(default_factory=dict),
    store: PrefsStoreProtocol = Depends(get_store),
) -> dict[str, Any]:
    # Whitelist fields. Unknown keys are silently ignored — a newer
    # client may send fields the server hasn't learned yet; we don't
    # want to 400 on that.
    kwargs: dict[str, Any] = {}
    if "system_prompt_addition" in body:
        v = body["system_prompt_addition"]
        if not isinstance(v, str):
            raise HTTPException(
                status_code=400,
                detail="system_prompt_addition must be a string",
            )
        # Length cap: this text goes into every request, so a runaway
        # 1MB string would balloon cost. 8 KiB is well beyond any
        # realistic business prompt and well within token budget.
        if len(v) > 8 * 1024:
            raise HTTPException(
                status_code=400,
                detail="system_prompt_addition is too long (max 8 KiB)",
            )
        kwargs["system_prompt_addition"] = v
    if not kwargs:
        raise HTTPException(status_code=400, detail="no recognized fields to update")
    prefs = await store.update(**kwargs)
    logger.info("prefs.updated fields=%s", ",".join(kwargs.keys()))
    return prefs.to_dict()
