$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "Starting agent-project with Docker Compose..."
docker compose up -d --build

Write-Host ""
Write-Host "Services:"
docker compose ps

Write-Host ""
Write-Host "Open these URLs:"
Write-Host "  Frontend:       http://localhost:8501"
Write-Host "  Backend:        http://localhost:8000"
Write-Host "  Backend health: http://localhost:8000/health"
Write-Host "  Airflow:        http://localhost:8080"
Write-Host "  MinIO console:  http://localhost:9001"
