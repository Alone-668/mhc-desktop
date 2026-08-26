"""Tests for the fail-closed auth policy in ``create_app``.

Before the refactor, ``create_app()`` happily booted an app
without an auth provider — every endpoint was public. The fail-
closed contract says: in non-debug mode, missing ``auth=`` must
crash the boot loud rather than silently shipping an unauthenticated
service. The deploy package's ``build_default_app()`` defaults to
``MockAuthProvider`` so the convenience call still works; the
constraint only bites callers who try to override ``auth=None``
explicitly.
"""

from __future__ import annotations

import pytest

from mhc_desktop_backend import create_app
from mhc_desktop_backend.config import Config


def test_create_app_in_debug_mode_allows_no_auth():
    """Debug mode is the historical "no IdP needed" path; still
    works without an auth kwarg so local iteration doesn't require
    spinning up a mock IdP."""
    cfg = Config(debug=True, host="127.0.0.1", port=8765)
    app = create_app(config=cfg)
    assert app is not None


def test_create_app_in_production_requires_auth():
    """Production mode (debug=False) without auth must fail loud."""
    cfg = Config(debug=False, host="127.0.0.1", port=8765)
    with pytest.raises(RuntimeError, match="auth provider is required"):
        create_app(config=cfg)


def test_create_app_in_production_with_auth_succeeds():
    """Production mode WITH auth works fine — the constraint is
    specifically about missing auth, not about any other missing
    store / manager."""
    from mhc_desktop_backend.protocols import AuthProviderProtocol

    class _FakeAuth(AuthProviderProtocol):
        async def login(self, username, password):
            return None

        async def resolve(self, token):
            return None

        async def logout(self, token):
            return None

    cfg = Config(debug=False, host="127.0.0.1", port=8765)
    app = create_app(config=cfg, auth=_FakeAuth())
    assert app is not None


def test_default_debug_mode_does_not_raise():
    """The kernel default config is ``debug=True`` so importing the
    module / calling ``create_app()`` from ad-hoc code paths doesn't
    require auth. Regression: nobody wants a regression to
    ``debug=False`` default to suddenly break the dev workflow.
    """
    app = create_app()
    assert app is not None
