# mhc-desktop

A self-hosted Skill/MCP agent client. The user picks an LLM provider, drops
in Skills (folders of context + scripts), wires MCP servers (subprocesses
that the model can call), and chats — the model streams responses, emits
tool calls, and uses whatever the user's stack exposes.

## Layout

```
.
├── mhc-desktop-backend/    Python FastAPI kernel — HTTP/SSE API, chat loop,
│                          storage Protocols, auth, tool execution contract
├── mhc-desktop-deploy/    Concrete defaults — file-backed stores,
│                          MockAuthProvider, build_default_app(...)
├── mhc-desktop-frontend/  Vue 3 + Vite SPA (Pinia, vue-router)
├── mhc-desktop-app/       Electron host — spawns bundled Python backend,
│                          serves SPA from same origin
├── scripts/               build-spa, build-bundled-python, dev loop
├── docs/                  packaging + content-pack authoring
└── e2e/                   17-check post-refactor HTTP smoke
```

## Quick start (dev)

```bash
# 1. Install backend deps (uses uv workspace)
uv sync --all-packages

# 2. Run backend + frontend dev loop (separate terminals)
bash scripts/dev-mhc-desktop.sh    # backend on :8765, frontend on :5180
cd mhc-desktop-frontend && npm run dev
```

Default auth ships three demo users (`alice/wonderland`, `bob/builder`,
`demo/demo`) so you can poke at the login flow without an IdP.

## Quick start (production)

```bash
# Build the SPA into the backend wheel's static/ dir
bash scripts/build-spa.sh          # or build-spa.ps1 on Windows

# Build the bundled Python (PBS + minimal-harness + desktop wheel)
bash scripts/build-bundled-python.sh    # builds packages/mhc-desktop-app/build-resources/backend/

# Package the Electron installer
cd mhc-desktop-app
npm install
npm run package                    # → dist/mhc-desktop Setup *.exe (NSIS)
```

## Architecture

The backend is split into two layers:

- **`mhc-desktop-backend` (kernel)**: a `create_app(**kwargs)` factory with
  ~25 Protocol slots (`SessionStoreProtocol`, `ProviderStoreProtocol`,
  `AuthProviderProtocol`, `ToolExecutorRegistryProtocol`, …). The kernel
  refuses to boot without an auth provider in non-debug mode (fail-closed).
  This is the only package that contains the chat loop and the HTTP/SSE
  surface — everything else is config.

- **`mhc-desktop-deploy` (shell)**: ships file-backed stores, a mock
  auth provider, and `build_default_app(**overrides)` which wires every
  default. Enterprise forks typically override a few kwargs (auth, scope
  rules, storage, presets) without touching the kernel.

The frontend is a Vue 3 SPA served by the backend on the same origin
(so `/api/v1/...` is relative — no CORS, no `file://` pitfalls). The
Electron host only adds a window chrome, port probing, and bundled-Python
spawn.

## External dependencies

| Package          | Where it comes from |
| ---------------- | ------------------- |
| `minimal-harness` | PyPI (aliyun mirror), `>=0.8.1a6,<0.9` |
| `fastapi`         | PyPI |
| `openai`          | PyPI |
| `anthropic`       | PyPI |
| `vue`, `pinia`, … | npm (CDN-already-mirrored) |

## End-to-end verification

```bash
# 1. Boot the backend
(python -m mhc_desktop_deploy &) ; sleep 5

# 2. Run the smoke (no screenshots, just HTTP)
node e2e/smoke.cjs

# 3. Tear down
pkill -f mhc_desktop_deploy
```

Expected: `17 passed, 0 failed`.

## Documentation

- [docs/PACKAGING.md](docs/PACKAGING.md) — NSIS installer build,
  electron-builder traps, PBS vs venv, China-mirror tips
- [docs/BUILTIN-CONTENT.md](docs/BUILTIN-CONTENT.md) — adding bundled
  Skills / Tools / MCPs
- [mhc-desktop-backend/README.md](mhc-desktop-backend/README.md) — kernel
  API reference
- [mhc-desktop-deploy/README.md](mhc-desktop-deploy/README.md) — enterprise
  integration guide (auth, storage, RBAC, presets, branding, content packs)