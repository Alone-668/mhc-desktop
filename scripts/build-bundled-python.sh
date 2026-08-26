#!/usr/bin/env bash
# Build the portable backend bundle (Python with deps installed into the
# PBS base interpreter's own site-packages) and stage it under
# mhc-desktop-app/build-resources/backend/.
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
APP="$ROOT/mhc-desktop-app"
OUT="$APP/build-resources/backend"
PBS_VER="20240909"
PY_VER="3.12.6"
PBS_TGZ="cpython-${PY_VER}+${PBS_VER}-x86_64-pc-windows-msvc-install_only.tar.gz"
# Try the npmmirror (Chinese mirror, fastest) first, fall back to
# GitHub direct, fall back to gh-proxy. Direct GitHub frequently
# times out from China.
PBS_URLS=(
    "https://registry.npmmirror.com/-/binary/python-build-standalone/${PBS_VER}/${PBS_TGZ}"
    "https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_VER}/${PBS_TGZ}"
    "https://gh-proxy.com/https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_VER}/${PBS_TGZ}"
)
CACHE="$ROOT/.build"

mkdir -p "$OUT" "$CACHE"

if [ ! -x "$OUT/python/python.exe" ]; then
    echo "[bundled-py] downloading PBS ${PY_VER}+${PBS_VER}"
    ok=0
    for url in "${PBS_URLS[@]}"; do
        echo "[bundled-py]   trying $url"
        if curl -L --fail --max-time 60 -o "$CACHE/$PBS_TGZ" "$url"; then
            ok=1
            break
        fi
    done
    if [ "$ok" -ne 1 ]; then
        echo "[bundled-py] ERROR: all PBS mirrors failed" >&2
        exit 1
    fi
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
# Try aliyun first (fastest in China), fall back to PyPI official
# (aliyun mirrors may lag behind official PyPI by a few minutes for
# newly-published versions of mhc-desktop-backend / mhc-desktop-deploy).
# Two non-obvious pins:
#   --prerelease=allow  -> minimal-harness is on a 0.8.1a6 alpha tag
#   "httpx<1.0"        -> PyPI's latest httpx is 1.0.dev5, which
#                          removes AsyncClient. Cap on stable.
for idx in "https://mirrors.aliyun.com/pypi/simple/" "https://pypi.org/simple/"; do
    if uv pip install --python "$OUT/python/python.exe" \
        --index-url "$idx" \
        --prerelease=allow \
        "httpx<1.0" \
        minimal-harness mhc-desktop-backend mhc-desktop-deploy \
        >/dev/null 2>&1; then
        echo "[bundled-py]   pulled backend deps from $idx"
        break
    fi
done

echo "[bundled-py] backend ready: $(du -sh "$OUT/python" | tr '\n' ' ')"