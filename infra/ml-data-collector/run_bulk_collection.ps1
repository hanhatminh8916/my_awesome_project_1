<#
.SYNOPSIS
    Phase 5 — Bulk real data collection từ Prometheus
    Kéo lịch sử + chạy 12 kịch bản đa dạng.

.PARAMETER Output
    File CSV đầu ra (default: bulk_training_data.csv)
.PARAMETER MergeTo
    Merge vào training_data.csv sau khi xong (default: ..\..\..\model\training_data.csv)
.PARAMETER HistoryHours
    Số giờ lịch sử cần pull (default: 72)
.PARAMETER HistoryOnly
    Chỉ kéo lịch sử, không chạy scenarios
.PARAMETER ScenariosOnly
    Chỉ chạy scenarios, không kéo lịch sử
.PARAMETER ScenarioMin
    Số phút thu thập mỗi scenario (default: 3)
#>
param(
    [string]$Output        = "$PSScriptRoot\bulk_training_data.csv",
    [string]$MergeTo       = "$PSScriptRoot\..\..\model\training_data.csv",
    [int]   $HistoryHours  = 72,
    [switch]$HistoryOnly,
    [switch]$ScenariosOnly,
    [int]   $ScenarioMin   = 3,
    [string]$PromUrl       = "http://localhost:9090"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Python (dùng model/.venv nếu có) ─────────────────────────────────────────
$venv   = Resolve-Path "$PSScriptRoot\..\..\model\.venv\Scripts\python.exe" -ErrorAction SilentlyContinue
$python = if ($venv) { $venv.Path } else { "python" }
Write-Host "[setup] Python : $python"
Write-Host "[setup] Output : $Output"
Write-Host "[setup] MergeTo: $MergeTo"

# ── Install/update dependencies ───────────────────────────────────────────────
$req = Join-Path $PSScriptRoot "requirements.txt"
if (Test-Path $req) {
    Write-Host "`n[pip] Installing requirements (skip if already installed)…"
    & $python -m pip install -q --no-deps --exists-action i -r $req 2>$null
    if ($LASTEXITCODE -ne 0) {
        & $python -m pip install -q -r $req
    }
}

# ── Start Prometheus port-forward ─────────────────────────────────────────────
Write-Host "`n[k8s] Starting port-forward svc/prometheus 9090:9090 …"
$pf = Start-Process -FilePath "kubectl" `
    -ArgumentList "port-forward svc/prometheus -n monitoring 9090:9090" `
    -PassThru -WindowStyle Minimized
Write-Host "[k8s] Port-forward PID: $($pf.Id)"
Start-Sleep -Seconds 6

# Quick connectivity check
try {
    $null = Invoke-RestMethod "$PromUrl/api/v1/query?query=up" -TimeoutSec 5
    Write-Host "[ok]  Prometheus reachable at $PromUrl"
} catch {
    Write-Warning "Cannot reach Prometheus — port-forward may have failed."
    Write-Warning "Start manually:  kubectl port-forward svc/prometheus -n monitoring 9090:9090"
}

# ── Build argument list ───────────────────────────────────────────────────────
$script     = Join-Path $PSScriptRoot "bulk_collector.py"
$mergeArg   = if (Test-Path $MergeTo) { @("--merge", $MergeTo) } else { @() }
$modeArgs   = @()
if ($HistoryOnly)   { $modeArgs += "--no-scenarios" }
if ($ScenariosOnly) { $modeArgs += "--no-history" }

$allArgs = @(
    $script
    "--prom-url",      $PromUrl
    "--output",        $Output
    "--history-hours", $HistoryHours
    "--scenario-min",  $ScenarioMin
) + $modeArgs + $mergeArg

# ── Run ──────────────────────────────────────────────────────────────────────
Write-Host "`n[run] Starting bulk_collector.py …`n"
try {
    & $python @allArgs
    $exitCode = $LASTEXITCODE
} finally {
    Write-Host "`n[k8s] Stopping port-forward (PID $($pf.Id)) …"
    Stop-Process -Id $pf.Id -Force -ErrorAction SilentlyContinue
}

if ($exitCode -eq 0) {
    Write-Host "`n[done] ✓ Bulk collection complete."
    if (Test-Path $MergeTo) {
        $rows = (Import-Csv $MergeTo).Count
        Write-Host "[done] training_data.csv now has $rows rows."
    }
} else {
    Write-Error "bulk_collector.py exited with code $exitCode"
}
