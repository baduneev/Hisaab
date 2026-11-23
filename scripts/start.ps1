param([switch]$NoInstall)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
if (-not $NoInstall) {
  if (-not (Test-Path .venv)) { python -m venv .venv }
  & ./.venv/Scripts/python.exe -m pip install -r requirements.lock.txt
  if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed' }
  npm ci
  if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed' }
  npm run build
  if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
}
docker compose up -d --wait database
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL startup failed' }
& ./.venv/Scripts/python.exe -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw 'Database migration failed' }
Write-Host 'Open http://127.0.0.1:8008 after startup. Stop with Ctrl+C.'
& ./.venv/Scripts/python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8008 --workers 1
