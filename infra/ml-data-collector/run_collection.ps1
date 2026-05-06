<#
.SYNOPSIS
    Phase 5 data collection helper.
    Starts a Prometheus port-forward then runs the full simulation pipeline.

.USAGE
    .\run_collection.ps1 [-Scenarios normal,degraded,down] [-Output training_data.csv]
#>
param(
    [string]$Scenarios = "normal,degraded,down",
    [string]$Output    = "$PSScriptRoot\training_data.csv",
    [string]$PromUrl   = "http://localhost:9090"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Python executable (use model/.venv if available) ─────────────────────────
$venv    = Join-Path $PSScriptRoot "..\..\model\.venv\Scripts\python.exe"
$python  = if (Test-Path $venv) { $venv } else { "python" }

Write-Host "[setup] Python: $python"
Write-Host "[setup] Output: $Output"
Write-Host "[setup] Scenarios: $Scenarios"

# ── 1. Install requirements ───────────────────────────────────────────────────
$req = Join-Path $PSScriptRoot "requirements.txt"
if (Test-Path $req) {
    Write-Host "`n[pip] Installing requirements…"
    & $python -m pip install -q -r $req
}

# ── 2. Start Prometheus port-forward in background ───────────────────────────
Write-Host "`n[k8s] Starting port-forward svc/prometheus 9090:9090 …"
$pf = Start-Process -FilePath "kubectl" `
    -ArgumentList "port-forward svc/prometheus -n monitoring 9090:9090" `
    -PassThru -WindowStyle Minimized

Write-Host "[k8s] Port-forward PID: $($pf.Id)"
Start-Sleep -Seconds 6   # wait for tunnel to open

# ── 3. Quick connectivity check ──────────────────────────────────────────────
try {
    $null = Invoke-RestMethod "$PromUrl/api/v1/query?query=up" -TimeoutSec 5
    Write-Host "[ok]  Prometheus reachable at $PromUrl"
} catch {
    Write-Warning "Cannot reach Prometheus at $PromUrl — port-forward may have failed."
    Write-Warning "Start it manually:  kubectl port-forward svc/prometheus -n monitoring 9090:9090"
}

# ── 4. Run simulation ─────────────────────────────────────────────────────────
$sim = Join-Path $PSScriptRoot "simulate_scenarios.py"
Write-Host "`n[sim] Starting simulation (scenarios: $Scenarios) …`n"

try {
    & $python $sim --prom-url $PromUrl --output $Output --scenarios $Scenarios
} finally {
    # ── 5. Stop port-forward ─────────────────────────────────────────────────
    Write-Host "`n[k8s] Stopping port-forward (PID $($pf.Id)) …"
    Stop-Process -Id $pf.Id -Force -ErrorAction SilentlyContinue
    Write-Host "[done] Data saved to: $Output"
}
