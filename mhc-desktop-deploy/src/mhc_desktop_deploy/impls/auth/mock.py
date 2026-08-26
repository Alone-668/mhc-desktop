"""In-process reference :class:`AuthProviderProtocol`.

The mock keeps a token -> :class:`AuthUser` map in process memory and
seeds three demo accounts so reviewers can poke at the login flow
without setting up an IdP.

Pre-seeded accounts (username / password):

* ``alice`` / ``wonderland`` — Alice Liddell
* ``bob`` / ``builder`` — Bob the Builder
* ``demo`` / ``demo`` — generic user

For real deployments, swap this out for an OIDC / LDAP / OAuth
adapter that implements the same Protocol; the rest of the system
doesn't care.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass

from mhc_desktop_backend.protocols import AuthProviderProtocol, AuthUser

logger = logging.getLogger("mhc_desktop_backend")


@dataclass(frozen=True)
class _Account:
    """A seeded demo user: id, password, display name, avatar URL."""

    user: AuthUser
    password: str


_SEED: tuple[_Account, ...] = (
    _Account(
        AuthUser(
            id="u-alice",
            username="alice",
            display_name="Alice Liddell",
            avatar_url=None,
        ),
        "wonderland",
    ),
    _Account(
        AuthUser(
            id="u-bob",
            username="bob",
            display_name="Bob the Builder",
            avatar_url=None,
        ),
        "builder",
    ),
    _Account(
        AuthUser(
            id="u-demo",
            username="demo",
            display_name="Demo User",
            avatar_url=None,
        ),
        "demo",
    ),
)


class MockAuthProvider(AuthProviderProtocol):
    """Process-local token registry.

    The store is a single ``dict`` guarded by an asyncio lock. Tokens
    are 24-byte URL-safe random strings (``secrets.token_urlsafe``).
    Logout removes the entry — no expiry otherwise.

    ponytail: global lock, in-process state. Per-account locks or a
    persistent token store (Redis / DB) is the upgrade path when
    multi-process / multi-host comes up.
    """

    def __init__(self) -> None:
        # ``id(AuthUser)`` carries enough identity for our purposes;
        # building a fresh AuthUser on every ``resolve`` is fine for a
        # mock and keeps the dataclass immutable.
        self._tokens: dict[str, AuthUser] = {}
        self._lock = asyncio.Lock()
        self._by_username: dict[str, _Account] = {
            acct.user.username: acct for acct in _SEED
        }

    async def login(self, username: str, password: str) -> tuple[str, AuthUser] | None:
        """Verify a username/password pair and mint a fresh token.

        Returns ``None`` on any failure (unknown user OR bad password)
        — we don't distinguish, to avoid leaking which usernames are
        valid (an account-enumeration hardening).
        """
        acct = self._by_username.get(username.strip().lower())
        if acct is None or acct.password != password:
            logger.info("auth.login.failed user=%s", username)
            return None
        token = secrets.token_urlsafe(24)
        async with self._lock:
            self._tokens[token] = acct.user
        logger.info("auth.login.ok user=%s", username)
        return token, acct.user

    async def resolve(self, token: str) -> AuthUser | None:
        """Return the principal for a live token, ``None`` otherwise.

        Read-only — no lock needed for a dict lookup. If we ever
        support expiring tokens we will revisit (mutating an LRU cache
        under contention is fine but dict.pop-then-set is not).
        """
        if not token:
            return None
        return self._tokens.get(token)

    async def logout(self, token: str) -> None:
        """Invalidate a token. Subsequent ``resolve`` calls return None.

        Safe to call with an unknown token — the dict just won't
        change.
        """
        async with self._lock:
            self._tokens.pop(token, None)
        logger.info("auth.logout token_present=%s", bool(token))


__all__ = ["MockAuthProvider"]
