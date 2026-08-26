#!/usr/bin/env bash
# Build the portable backend bundle (Python with deps installed into the
# PBS base interpreter's own site-packages) and stage it under
# packages/mhc-desktop-app/build-resources/backend/.
# Run once before `electron-builder --win`. Rebuild when backend deps
# or Python version bump.
#
# IMPORTANT: no venv layer. `python -m venv` writes pyvenv.cfg with the
# *absolute* build-machine path as `home`; the venv launcher dies with
# exit 103 ("No Python at") on any other machine. CPython 3.12 doesn't
# accept a relative `home`, so a venv can never be relocatable. Instead
# we install deps directly into the PBS base interpreter's own
# Lib/site-packages and run python/python.exe — sys.prefix then follows
# the executable location, so the bundle works wherever it ends up.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/packages/mhc-desktop-app"
OUT="$APP/build-resources/backend"
PBS_VER="20240909"
PY_VER="3.12.6"
PBS_TGZ="cpython-${PY_VER}+${PBS_VER}-x86_64-pc-windows-msvc-install_only.tar.gz"
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_VER}/${PBS_TGZ}"
CACHE="$ROOT/.build"

mkdir -p "$OUT" "$CACHE"

if [ ! -x "$OUT/python/python.exe" ]; then
    echo "[bundled-py] downloading $PBS_URL"
    curl -L --fail -o "$CACHE/$PBS_TGZ" "$PBS_URL"
    mkdir -p "$CACHE/pbs"
    tar -xzf "$CACHE/$PBS_TGZ" -C "$CACHE/pbs"
    rm -rf "$OUT/python"
    cp -R "$CACHE/pbs/python" "$OUT/python"
    # Drop .pdb files — saves ~60 MB with no runtime impact.
    find "$OUT/python" -name "*.pdb" -size +1k -delete
fi

if [ -d "$OUT/venv" ]; then
    echo "[bundled-py] removing stale venv"
    rm -rf "$OUT/venv"
fi

echo "[bundled-py] installing backend deps into python/Lib/site-packages"
uv pip install --python "$OUT/python/python.exe" \
    --index-url https://mirrors.aliyun.com/pypi/simple/ \
    minimal-harness mhc-desktop-backend mhc-desktop-deploy \
    >/dev/null

echo "[bundled-py] backend ready: $(du -sh "$OUT/python" | tr '\n' ' ')"