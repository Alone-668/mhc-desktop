"""Provider CRUD + presets router.

Endpoints:
* ``GET    /api/v1/providers``           — list configured providers (api_key masked)
* ``GET    /api/v1/providers/{name}``    — fetch one (api_key masked)
* ``POST   /api/v1/providers``           — create from body or ``preset_id`` query
* ``PUT    /api/v1/providers/{name}``    — update fields
* ``DELETE /api/v1/providers/{name}``    — remove
* ``GET    /api/v1/providers/presets``   — list built-in presets
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from mhc_desktop_backend.protocols import ProviderStoreProtocol

logger = logging.getLogger("mhc_desktop_backend")

router = APIRouter(prefix="/api/v1/providers", tags=["providers"])


def get_store(request: Request) -> ProviderStoreProtocol:
    store: ProviderStoreProtocol | None = getattr(
        request.app.state, "provider_store", None
    )
    if store is None:
        raise HTTPException(status_code=503, detail="provider store not initialized")
    return store


def _validate(payload: dict[str, Any], allowed: set[str]) -> None:
    ptype = payload.get("provider_type", "openai")
    if allowed and ptype not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported provider_type: {ptype}",
        )


def _get_presets(request: Request) -> list:
    return list(getattr(request.app.state, "provider_presets", []) or [])


def _get_allowed_types(request: Request) -> set[str]:
    return set(getattr(request.app.state, "provider_types", set()) or set())


@router.get("/presets")
async def list_presets(request: Request) -> list[dict[str, Any]]:
    # Preset list is deploy-provided (kernel ships a default six;
    # deploys can replace via ``create_app(provider_presets=...)``).
    return [p.to_dict() for p in _get_presets(request)]


@router.get("")
async def list_providers(
    store: ProviderStoreProtocol = Depends(get_store),
) -> list[dict[str, Any]]:
    providers = await store.list()
    return [p.public_dict() for p in providers]


@router.get("/{name}")
async def get_provider(
    name: str, store: ProviderStoreProtocol = Depends(get_store)
) -> dict[str, Any]:
    p = await store.get(name)
    if p is None:
        raise HTTPException(status_code=404, detail=f"provider '{name}' not found")
    return p.public_dict()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_provider(
    request: Request,
    body: dict[str, Any],
    preset_id: str | None = Query(default=None),
    store: ProviderStoreProtocol = Depends(get_store),
) -> dict[str, Any]:
    presets = _get_presets(request)
    if preset_id:
        preset = next((p for p in presets if p.id == preset_id), None)
        if preset is None:
            raise HTTPException(status_code=400, detail=f"unknown preset '{preset_id}'")
        # Seed body from preset; user-supplied fields win.
        seeded = {
            "name": preset.id,
            "provider_type": preset.provider_type,
            "base_url": preset.base_url,
            "default_model": preset.default_model,
            "models": list(preset.models),
            "description": preset.description,
        }
        seeded.update(body)
        body = seeded
    _validate(body, _get_allowed_types(request))
    try:
        provider = await store.create(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return provider.public_dict()


@router.put("/{name}")
async def update_provider(
    request: Request,
    name: str,
    body: dict[str, Any],
    store: ProviderStoreProtocol = Depends(get_store),
) -> dict[str, Any]:
    _validate(body, _get_allowed_types(request))
    # api_key is masked on read (***abcd). On PUT the frontend
    # cannot send back the real value, so accept empty or the
    # masked pattern as "keep the existing key" — otherwise the
    # user would be forced to re-type it on every edit.
    incoming = body.get("api_key", "")
    if isinstance(incoming, str) and (not incoming or incoming.startswith("***")):
        body.pop("api_key", None)
    try:
        provider = await store.update(name, body)
    except ValueError as e:
        msg = str(e)
        code = 404 if "not found" in msg else 400
        raise HTTPException(status_code=code, detail=msg) from None
    return provider.public_dict()


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    name: str, store: ProviderStoreProtocol = Depends(get_store)
) -> None:
    try:
        await store.delete(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
