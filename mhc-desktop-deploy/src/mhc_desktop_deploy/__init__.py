"""mhc-desktop-deploy — deployment shell for the mhc-desktop kernel.

This package owns:

* The default file-backed concrete implementations of every Protocol in
  :mod:`mhc_desktop_backend.protocols` (sessions, providers, skills,
  MCP, tools, prefs, metrics, stream registry).
* The default :class:`MockAuthProvider` for the auth Protocol.

End-users fork this package (or write a sibling one) to swap any
implementation for their enterprise backend — typically a Postgres
session store, a Vault-backed provider store, an LDAP/OIDC auth
provider. Everything above this layer (HTTP routes, MCP client,
tool call machinery, SSE chat loop) lives in the backend kernel
whl and never has to change.
"""

from __future__ import annotations

__version__ = "0.1.0"

# ``build_default_app`` is intentionally NOT imported here. Pulling
# every concrete store just because a downstream caller wrote
# ``import mhc_desktop_deploy`` would defeat the purpose of having
# a slim deploy package; ``assemble.build_default_app()`` does the
# imports on demand inside the function body.
#
# Importers that want the wiring function should reach for it
# explicitly::
#
#     from mhc_desktop_deploy.assemble import build_default_app

__all__ = ["__version__"]
