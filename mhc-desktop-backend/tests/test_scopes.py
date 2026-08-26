"""Tests for the RBAC scope seam in :mod:`mhc_desktop_backend.auth.middleware`.

The kernel's auth middleware accepts a ``scope_required_for`` callable
that maps a request path to the set of scopes a user must hold. The
deploy package decides the actual vocabulary (e.g.
``"metrics:read"`` for the dashboard, ``"admin"`` for management).
The kernel only enforces subset-of-scopes on
``AuthUser.scopes``.

These tests pin:

* the user dataclass carries ``scopes`` (default empty frozenset)
* the middleware rejects requests that lack the required scopes
* the middleware allows requests that hold a superset
* the middleware still works without ``scope_required_for`` (no
  scope enforcement — legacy behaviour)
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mhc_desktop_backend.app import create_app
from mhc_desktop_backend.auth.middleware import (
    DEFAULT_EXEMPT_PATHS,
    install_auth,
)
from mhc_desktop_backend.protocols import (
    AuthProviderProtocol,
    AuthUser,
)


class _ScopeAuth(AuthProviderProtocol):
    """Auth provider that maps three demo users to specific scope sets."""

    def __init__(self) -> None:
        self._tokens: dict[str, AuthUser] = {
            "admin-token": AuthUser(
                id="u-admin",
                username="admin",
                display_name="Admin",
                scopes=frozenset({"admin", "metrics:read"}),
            ),
            "reader-token": AuthUser(
                id="u-reader",
                username="reader",
                display_name="Reader",
                scopes=frozenset({"metrics:read"}),
            ),
            "nobody-token": AuthUser(
                id="u-nobody",
                username="nobody",
                display_name="Nobody",
                scopes=frozenset(),
            ),
        }

    async def login(self, username, password):
        return None

    async def resolve(self, token):
        return self._tokens.get(token)

    async def logout(self, token):
        self._tokens.pop(token, None)


def _build_app(scope_required_for) -> FastAPI:
    """Build a minimal app with scope enforcement + a single test
    endpoint to exercise the middleware."""
    app = FastAPI()

    @app.get("/_scope-test")
    async def _scope_test():
        return {"ok": True}

    auth = _ScopeAuth()
    install_auth(
        app,
        auth,
        exempt_paths=(),
        scope_required_for=scope_required_for,
    )
    return app


def test_no_scope_callable_disables_scope_enforcement():
    """Without ``scope_required_for``, every authenticated user can
    hit every non-exempt path — legacy behaviour."""
    app = _build_app(scope_required_for=None)
    with TestClient(app) as c:
        r = c.get(
            "/_scope-test",
            headers={"Authorization": "Bearer nobody-token"},
        )
    assert r.status_code == 200


def test_scope_required_returns_403_when_user_lacks_scopes():
    """User without the required scope gets 403, not 401."""

    def rule(path: str) -> frozenset[str]:
        # Pretend the test endpoint needs admin.
        if path.startswith("/_scope-test"):
            return frozenset({"admin"})
        return frozenset()

    app = _build_app(scope_required_for=rule)
    with TestClient(app) as c:
        r = c.get(
            "/_scope-test",
            headers={"Authorization": "Bearer reader-token"},
        )
    assert r.status_code == 403
    assert "missing scope" in r.json()["detail"]


def test_scope_required_returns_200_when_user_has_scope():
    """User with the required scope gets through."""

    def rule(path: str) -> frozenset[str]:
        if path.startswith("/_scope-test"):
            return frozenset({"metrics:read"})
        return frozenset()

    app = _build_app(scope_required_for=rule)
    with TestClient(app) as c:
        r = c.get(
            "/_scope-test",
            headers={"Authorization": "Bearer reader-token"},
        )
    assert r.status_code == 200


def test_scope_superset_passes():
    """User with more scopes than required passes — superset
    is the usual case for admin users."""

    def rule(path: str) -> frozenset[str]:
        if path.startswith("/_scope-test"):
            return frozenset({"metrics:read"})
        return frozenset()

    app = _build_app(scope_required_for=rule)
    with TestClient(app) as c:
        r = c.get(
            "/_scope-test",
            headers={"Authorization": "Bearer admin-token"},
        )
    assert r.status_code == 200


def test_no_scopes_user_cannot_access_scope_protected_route():
    """A user with empty scopes hitting any scope-protected route
    gets 403, never 401 (the token is valid)."""

    def rule(path: str) -> frozenset[str]:
        return frozenset({"any"})

    app = _build_app(scope_required_for=rule)
    with TestClient(app) as c:
        r = c.get(
            "/_scope-test",
            headers={"Authorization": "Bearer nobody-token"},
        )
    assert r.status_code == 403


def test_default_exempt_paths_include_meta():
    """Sanity: ``/api/v1/meta`` stays in the default exempt set so
    the forked frontend can read it pre-login."""
    assert "/api/v1/meta" in DEFAULT_EXEMPT_PATHS


def test_create_app_thread_scope_via_kwargs():
    """``create_app(scope_required_for=...)`` wires the rule through
    to the middleware. Proves the deploy-friendly kwargs surface
    from app.py actually plumbs the scope rule end-to-end."""

    def rule(path: str) -> frozenset[str]:
        # Lock down metrics reads to ``metrics:read`` only.
        if path.startswith("/api/v1/metrics"):
            return frozenset({"metrics:read"})
        return frozenset()

    # Build the full app via the canonical factory so we exercise
    # the kwargs surface the deploy package uses.
    app = create_app(
        auth=_ScopeAuth(),
        auth_exempt_paths=(),
        scope_required_for=rule,
    )
    with TestClient(app) as c:
        # Reader hits metrics -> passes scope gate (503 because the
        # metrics repo isn't wired — that's a separate concern).
        r = c.get(
            "/api/v1/metrics/summary",
            headers={"Authorization": "Bearer reader-token"},
        )
        assert r.status_code == 503  # scope passed, no repo
        # User with no scopes hits metrics -> 403, scope rejected
        # before the handler runs.
        r = c.get(
            "/api/v1/metrics/summary",
            headers={"Authorization": "Bearer nobody-token"},
        )
        assert r.status_code == 403
