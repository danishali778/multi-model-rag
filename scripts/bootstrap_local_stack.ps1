Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

Write-Warning "scripts/bootstrap_local_stack.ps1 is deprecated; use scripts/bootstrap_local_supabase_stack.ps1 instead."
& powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "bootstrap_local_supabase_stack.ps1")
exit $LASTEXITCODE
