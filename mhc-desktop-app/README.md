# mhc-desktop-app

Electron host shell for the mhc-desktop Skill/MCP client.

## What it does

- Spawns the Python backend as a child process. Production: launches
  the bundled PBS interpreter `resources/backend/python/python.exe`
  (deps baked into its own `Lib/site-packages` — deliberately **no
  venv**, see below). Dev: launches `uv run -m mhc_desktop_backend`
  (if `--mhc-force-uv`).
- Probes 8765..8770 with `net.createServer` to pick a free port
  before asking the backend to bind
- Waits for `/ready` before opening the window
- Loads `http://127.0.0.1:<port>/` — the backend itself serves the SPA
  (see `mhc-desktop-backend/app.py::_mount_spa`) so the renderer sees
  the SPA at the same origin as `/api/v1/...`
- Forwards external link clicks to the system browser

## Dev

```bash
# 1. start backend + frontend dev loop (separate terminal)
bash scripts/dev-mhc-desktop.sh

# 2. in another terminal, start Electron pointing at the dev server
cd packages/mhc-desktop-app
npm install
npm run dev
```

`npm run dev` opens a 1180×760 window pointing at `http://127.0.0.1:5180`.
The Electron main process **does not** spawn the backend in dev mode —
the dev script already does that, and double-spawning would race.

## Production

```bash
# build the SPA
cd packages/mhc-desktop-frontend && npm run build

# build the Electron TypeScript
cd ../mhc-desktop-app && npm install && npm run build

# launch
npm start
```

## Packaging

```bash
# 1. build SPA into the backend's static/ dir
powershell scripts/build-spa.ps1          # or: bash scripts/build-spa.sh

# 2. (first time only) build the bundled Python
#    downloads python-build-standalone, pip-installs mhc-desktop-backend
#    + minimal-harness + mh-service-kit into its own site-packages.
#    Output goes to packages/mhc-desktop-app/build-resources/backend/
#
#    NO VENV ON PURPOSE: `python -m venv` writes pyvenv.cfg with the
#    absolute build-machine path as `home`; the venv launcher exits 103
#    ("No Python at") on any other machine, and CPython 3.12 rejects a
#    relative `home`. Installing into the base interpreter's own
#    site-packages keeps the bundle relocatable — sys.prefix follows
#    the exe location.
powershell scripts/build-bundled-python.ps1
#    bash equivalent:
bash scripts/build-bundled-python.sh

# 3. build & package the Electron host
cd packages/mhc-desktop-app
npm install
npm run build
npx electron-builder --win --x64         # NSIS installer
```

electron-builder outputs:

- Windows: NSIS installer (`dist/mhc-desktop Setup 0.1.0.exe`)
- macOS: DMG (notarization requires `CSC_LINK` / `CSC_KEY_PASSWORD` env)
- Linux: AppImage

### China mainland mirror env vars

The default electron-builder fetches Electron + electron-builder-binaries
from GitHub. Set these to route through the npmmirror CDN:

```bash
export ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/
export ELECTRON_BUILDER_BINARIES_MIRROR=https://npmmirror.com/mirrors/electron-builder-binaries/
```

### `winCodeSign` symlink workaround

Windows non-Developer-Mode users hit `7za` failures when extracting the
`winCodeSign` archive because the bundled `7za.exe` cannot create
symlinks for `darwin/10.12/lib/lib{crypto,ssl}.dylib`. The cache
shortcut: pre-extract once with `7za x -xr!darwin -xr!linux -xr!appxAssets`
into `%LOCALAPPDATA%\electron-builder\Cache\winCodeSign\winCodeSign-2.6.0\`
so subsequent runs reuse the cache.

Code signing certificates (`CSC_LINK` etc.) are configured via env vars
documented in electron-builder's docs.