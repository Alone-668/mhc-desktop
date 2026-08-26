# Build the portable backend bundle (Python + venv with deps installed)
# and stage it under packages/mhc-desktop-app/build-resources/backend/.
# Mirrors scripts/build-bundled-python.sh for Windows.
$ErrorActionPreference = "Stop"

$ROOT       = (Resolve-Path "$PSScriptRoot/..").Path
$APP        = Join-Path $ROOT "packages/mhc-desktop-app"
$OUT        = Join-Path $APP "build-resources\backend"
$PBS_VER    = "20240909"
$PY_VER     = "3.12.6"
$PBS_TGZ    = "cpython-${PY_VER}+${PBS_VER}-x86_64-pc-windows-msvc-install_only.tar.gz"
$PBS_URL    = "https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_VER}/${PBS_TGZ}"
$CACHE      = Join-Path $ROOT ".build"

New-Item -ItemType Directory -Force -Path $OUT, $CACHE | Out-Null

$pyExe = Join-Path $OUT "python\python.exe"
if (-not (Test-Path $pyExe)) {
    Write-Host "[bundled-py] downloading $PBS_URL"
    $tgz = Join-Path $CACHE $PBS_TGZ
    if (-not (Test-Path $tgz)) {
        Invoke-WebRequest -Uri $PBS_URL -OutFile $tgz -UseBasicParsing
    }
    $pbsRoot = Join-Path $CACHE "pbs"
    if (Test-Path $pbsRoot) { Remove-Item -Recurse -Force $pbsRoot }
    New-Item -ItemType Directory -Force -Path $pbsRoot | Out-Null
    tar -xzf $tgz -C $pbsRoot
    if (Test-Path (Join-Path $OUT "python")) { Remove-Item -Recurse -Force (Join-Path $OUT "python") }
    Copy-Item -Recurse -Force (Join-Path $pbsRoot "python") (Join-Path $OUT "python")
    # Drop .pdb files to shave ~60 MB.
    Get-ChildItem -Path (Join-Path $OUT "python") -Recurse -Filter "*.pdb" -File |
        Where-Object { $_.Length -gt 1KB } | Remove-Item -Force
}

$venvDir = Join-Path $OUT "venv"
# IMPORTANT: no venv layer. ``python -m venv`` writes ``pyvenv.cfg``
# with the *absolute* build-machine path as ``home``; the venv launcher
# (Scripts\python.exe) dies with exit 103 ("No Python at") on any other
# machine. CPython 3.12 doesn't accept a relative ``home``, so a venv can
# never be relocatable. Instead we install deps directly into the PBS
# base interpreter's own Lib\site-packages and run python\python.exe —
# sys.prefix then follows the executable location, so the bundle works
# wherever it ends up.
if (Test-Path $venvDir) {
    Write-Host "[bundled-py] removing stale venv"
    Remove-Item -Recurse -Force $venvDir -ErrorAction SilentlyContinue
}

Write-Host "[bundled-py] installing backend deps into python\Lib\site-packages"
uv pip install --python $pyExe --index-url https://mirrors.aliyun.com/pypi/simple/ `
    minimal-harness mhc-desktop-backend mhc-desktop-deploy | Out-Null

Write-Host "[bundled-py] backend ready"