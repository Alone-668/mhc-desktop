"""Standalone skill market service.

Identity comes from the mhc-desktop kernel proxy via HMAC-signed
headers (``X-MHC-User`` / ``X-MHC-TS`` / ``X-MHC-Sig``) — this service
has no accounts of its own. See ``auth.py``.
"""

from .app import create_app

__version__ = "0.1.0"
__all__ = ["__version__", "create_app"]
