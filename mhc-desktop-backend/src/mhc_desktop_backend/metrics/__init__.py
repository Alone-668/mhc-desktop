"""Usage-metrics package.

Three modules, each independent:

* :mod:`mhc_desktop_backend.metrics.types` — the wire-level records
  + response shapes (dataclasses only, no IO).
* :mod:`mhc_desktop_backend.metrics.protocols` — the
  :class:`MetricsRepositoryProtocol` contract deployments substitute.
* :mod:`mhc_desktop_backend.metrics.aggregations` — pure
  aggregation helpers (summary, ranking, trend) shared by every
  backend.

The default JSONL-backed implementation lives in
:mod:`mhc_desktop_backend.storage.metrics_store`. Custom backends
(SQLite, Postgres, Clickhouse, …) implement the protocol and are
plugged into :func:`mhc_desktop_backend.app.create_app` via the
``metrics=`` kwarg.
"""
