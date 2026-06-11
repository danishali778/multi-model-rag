Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Command
    )

    & $Command[0] $Command[1..($Command.Length - 1)]
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $($Command -join ' ')"
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "docker is required."
}
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "python is required."
}

Invoke-Step @("python", "scripts/validate_runtime_env.py", ".env.compose.dev", "remote-compose")
Invoke-Step @("python", "scripts/run_docker_compose.py", "-f", "docker-compose.yml", "-f", "docker-compose.dev.yml", "--env-file", ".env.compose.dev", "config")
Invoke-Step @("python", "scripts/run_docker_compose.py", "-f", "docker-compose.yml", "-f", "docker-compose.dev.yml", "--env-file", ".env.compose.dev", "up", "--build", "-d", "redis", "redis-exporter", "otel-collector", "prometheus", "grafana", "worker", "api")
Invoke-Step @("python", "scripts/wait_for_http.py", "http://localhost:8000/ready", "120")
Invoke-Step @("python", "scripts/run_docker_compose.py", "-f", "docker-compose.yml", "-f", "docker-compose.dev.yml", "--env-file", ".env.compose.dev", "exec", "-T", "api", "python", "scripts/verify_runtime_bootstrap.py")

Write-Host "Remote-Supabase dev Docker stack is ready."
Write-Host "- API: http://localhost:8000"
Write-Host "- Prometheus: http://localhost:9090"
Write-Host "- Grafana: http://localhost:3001"
Write-Host "- Live reload: enabled for API and worker source paths"
