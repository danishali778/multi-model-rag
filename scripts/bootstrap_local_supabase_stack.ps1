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

Invoke-Step @("python", "scripts/run_supabase_cli.py", "start", "--ignore-health-check")
Invoke-Step @("python", "scripts/generate_local_supabase_env.py", "compose", ".env.compose.local-supabase")
Invoke-Step @("python", "scripts/validate_runtime_env.py", ".env.compose.local-supabase", "local-supabase-compose")
$composeEnv = Get-Content .env.compose.local-supabase | Where-Object { $_ -match "=" } | ForEach-Object {
    $parts = $_ -split "=", 2
    [pscustomobject]@{ Key = $parts[0]; Value = $parts[1] }
}
$supabaseUrl = ($composeEnv | Where-Object Key -eq "SUPABASE_URL").Value
$serviceRoleKey = ($composeEnv | Where-Object Key -eq "SUPABASE_SERVICE_ROLE_KEY").Value
Invoke-Step @("python", "scripts/bootstrap_supabase_storage.py", $supabaseUrl, $serviceRoleKey, "raw-documents,processed-documents,voice-artifacts")
Invoke-Step @("python", "scripts/run_docker_compose.py", "--env-file", ".env.compose.local-supabase", "up", "--build", "-d", "redis", "redis-exporter", "otel-collector", "prometheus", "grafana", "worker", "api")
Invoke-Step @("python", "scripts/wait_for_http.py", "http://localhost:8000/ready", "120")
Invoke-Step @("python", "scripts/run_docker_compose.py", "--env-file", ".env.compose.local-supabase", "exec", "-T", "api", "python", "scripts/verify_runtime_bootstrap.py")

Write-Host "Local stack is ready."
Write-Host "- API: http://localhost:8000"
Write-Host "- Prometheus: http://localhost:9090"
Write-Host "- Grafana: http://localhost:3001"
