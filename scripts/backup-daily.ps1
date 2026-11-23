$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
& ./.venv/Scripts/python.exe scripts/backup.py create
if ($LASTEXITCODE -ne 0) { throw 'Hisaab daily encrypted backup failed' }
