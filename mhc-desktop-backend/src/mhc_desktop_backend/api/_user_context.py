"""Shared request-user lookup for API modules.

``request.state.user`` is populated by :func:`install_auth
<mhc_desktop_backend.auth.middleware.install_auth>` on every
non-exempt request. Both the chat and metrics modules read it the
same way; this is the one copy.
"""

from __future__ import annotations

from fastapi import Request


def current_user_id(request: Request) -> str:
    """The requesting user's username, or ``""`` for anonymous."""
    user = getattr(getattr(request, "state", None), "user", None)
    return getattr(user, "username", "") if user else ""