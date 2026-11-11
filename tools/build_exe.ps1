# Build script (ASCII only for Windows PowerShell 5.1 compatibility)
# Usage (run from anywhere):
#   .\tools\build_exe.ps1                 -> dist\Photo2Pet.exe
#   .\tools\build_exe.ps1 -Name MyPet     -> dist\MyPet.exe
param(
    [string]$Name = 'Photo2Pet'
)

$ErrorActionPreference = 'Stop'
$ROOT = Split-Path -Parent $PSScriptRoot
Set-Location $ROOT
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'
$env:EXE_NAME = $Name
$env:QT_QPA_PLATFORM = 'offscreen'

$py = Join-Path $ROOT '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $py)) {
    throw "Virtual environment not found: $py. Create .venv and install requirements-dev.txt first."
}

Write-Host '== 1/4 Refresh icons ==' -ForegroundColor Cyan
& $py (Join-Path $PSScriptRoot 'make_icon.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host '== 2/4 Smoke test ==' -ForegroundColor Cyan
& $py (Join-Path $ROOT '桌宠.py') '--smoke-test'
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host '== 3/4 Unit tests ==' -ForegroundColor Cyan
& $py -m unittest discover -s (Join-Path $ROOT 'tests')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host '== 4/4 PyInstaller build ==' -ForegroundColor Cyan
& $py -m PyInstaller --noconfirm (Join-Path $ROOT '桌宠.spec')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$dist = Join-Path $ROOT 'dist'
New-Item -ItemType Directory -Force -Path $dist | Out-Null
foreach ($doc in @('使用说明.txt', 'README.md')) {
    $src = Join-Path $ROOT $doc
    if (Test-Path -LiteralPath $src) {
        Copy-Item -LiteralPath $src -Destination (Join-Path $dist $doc) -Force
    }
}

$exe = Join-Path $dist "$Name.exe"
if (-not (Test-Path -LiteralPath $exe)) { throw "Build failed: $exe not found" }
$size = [math]::Round((Get-Item -LiteralPath $exe).Length / 1MB, 1)
Write-Host "Done: $exe ($size MB)" -ForegroundColor Green
