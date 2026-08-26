# mhc-desktop dev workflow (Windows, PowerShell)

The NSIS installer is for shipping. For day-to-day UI iteration:

## Terminal 1 — backend (hot reload via uvicorn WatchFiles)

```powershell
cd packages\mhc-desktop-backend
$env:MHC_PORT = 8770          # any free port; dev session uses 8770
uv run python -m mhc_desktop_backend
```

When `MHC_RELOAD=1` (default), uvicorn watches the package source and
reloads the worker process on save. The parent reloader process keeps
the listening port open across reloads, so the SPA keeps its session.

To kill: Ctrl+C. Avoid leaving zombie workers — close this terminal.

## Terminal 2 — frontend (HMR)

```powershell
cd packages\mhc-desktop-frontend
$env:MHC_BACKEND = "http://127.0.0.1:8770"   # MUST match Terminal 1's MHC_PORT
npm run dev
```

Vite serves on `http://127.0.0.1:5180` with HMR. Save a `.vue` or `.ts`
file; the Electron window updates without a reload.

The `MHC_BACKEND` env var sets the proxy target for `/api` and `/ready`.
**Always set it explicitly** — the default is `127.0.0.1:8765`, which is
usually an orphan left by an earlier session. If you skip this and your
real backend is on another port, the SPA silently talks to the wrong
backend and you'll see 404 / `Method Not Allowed` on routes that exist.

## Terminal 3 — Electron

```powershell
cd packages\mhc-desktop-app
$env:MHC_FORCE_UV = "uv"      # use uv run, not the bundled PBS python
$env:MHC_PORT = 8770          # must match Terminal 1
$env:MHC_DEV_URL = "http://127.0.0.1:5180"   # vite URL
npm run dev
```

`npm run dev` runs `tsc && electron . --mhc-dev-url …` so edits to
`main.ts` / `preload.ts` take effect after a manual restart of Electron
itself (Ctrl+C then `npm run dev` again).

The Electron window loads SPA from the vite URL and the backend from
whatever port `MHC_PORT` points at (default 8765). In dev mode Electron
**does not** spawn its own backend — it expects one to already be running.

## What changes when

| edit | reload strategy |
|---|---|
| `*.vue` / `*.ts` (frontend) | HMR (instant) |
| `main.ts` / `preload.ts` (Electron main) | Ctrl+C + `npm run dev` |
| backend `*.py` | uvicorn WatchFiles reload (~1-2 s) |
| backend Python deps (`pyproject.toml`) | Ctrl+C + re-`uv run` |
| NSIS installer | `npm run package` (only when shipping) |

## Troubleshooting

* **`Method Not Allowed` on `/api/v1/skills/import-bulk`** — the backend
  you are talking to is running stale code. Check the source file is
  saved, then watch the backend log for `WatchFiles detected changes ...
  Reloading...`. If it doesn't appear, the import-bulk endpoint is
  missing from the running code (older build).
* **`Port 8765 already in use`** — set `MHC_PORT=8770` (or any free
  port) consistently in Terminals 1 and 3.
* **Tool calls fail with `class=NotImplementedError`** — uvicorn picks
  SelectorEventLoop on Windows when `reload=True` (dev mode), and
  Selector loops can't spawn subprocesses, which the PowerShell tool
  needs. `main.py` forces ProactorEventLoop via a custom loop factory,
  so this is fixed — but a stale backend process running pre-fix code
  still fails. Restart Terminal 1 to pick up the fix.
* **No app window appears** — check Terminal 3 for `[backend] spawning
  …` lines; in dev mode Electron skips spawning, so if you forgot to
  start Terminal 1 the window opens but never reaches `/ready`.
* **Stale `mhc-desktop.log` showing old timestamps** — the file lives at
  `%APPDATA%\mhc-desktop-app\mhc-desktop.log`. The dev backend's
  startup log goes to `%TEMP%\mhc-desktop-backend.log` instead.