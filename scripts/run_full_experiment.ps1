# SkyGrid Enterprise — Full Experiment Reproducibility Script
# ============================================================
# Runs the complete experiment pipeline from a clean state:
#   1. Install Python dependencies
#   2. Run automated test suite (must pass before experiments)
#   3. Generate synthetic ML training data (seed=42)
#   4. Prepare train/val/test splits
#   5. Train ML models and select best
#   6. Run benchmark comparison (3 strategies x 10 scenarios)
#   7. Print summary results
#
# Requirements: Python 3.10+, pip installed
# Usage:        .\scripts\run_full_experiment.ps1
# Expected time: 2-4 minutes on a modern CPU

param(
    [int]$BenchScenarios = 10,
    [int]$BenchOrders    = 5,
    [int]$Seed           = 42,
    [int]$MLSamples      = 5000
)

$ErrorActionPreference = "Stop"
$StartTime = Get-Date

function Write-Step {
    param([string]$msg)
    Write-Host ""
    Write-Host "══════════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "  $msg" -ForegroundColor Cyan
    Write-Host "══════════════════════════════════════════" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$msg)
    Write-Host "  ✅ $msg" -ForegroundColor Green
}

function Write-Fail {
    param([string]$msg)
    Write-Host "  ❌ $msg" -ForegroundColor Red
}

# Ensure we're in project root
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot
Write-Host "`n[SkyGrid] Experiment Runner — $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Magenta

# ── Step 1: Install dependencies ──────────────────────────────────────
Write-Step "Step 1/6: Install Python dependencies"
try {
    pip install -r backend/requirements.txt -q
    Write-Success "Dependencies installed"
} catch {
    Write-Fail "pip install failed: $_"
    exit 1
}

# ── Step 2: Run tests ─────────────────────────────────────────────────
Write-Step "Step 2/6: Run automated test suite"
try {
    $TestResult = python -m pytest backend/tests/test_core.py -v --tb=short 2>&1
    $TestOutput = $TestResult -join "`n"
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "Tests FAILED. Aborting experiment."
        Write-Host $TestOutput
        exit 1
    }
    $PassLine = ($TestResult | Select-String "passed").Line
    Write-Success "All tests passed: $PassLine"
} catch {
    Write-Fail "Test runner failed: $_"
    exit 1
}

# ── Step 3: Generate training data ────────────────────────────────────
Write-Step "Step 3/6: Generate synthetic ML training data"
New-Item -ItemType Directory -Force -Path "backend\ml\data" | Out-Null
try {
    python backend/ml/data_generation.py --samples $MLSamples --seed $Seed --output backend/ml/data/raw_episodes.csv 2>&1 | Where-Object { $_ -notmatch "^python :" }
    Write-Success "Generated $MLSamples episodes to backend/ml/data/raw_episodes.csv"
} catch {
    Write-Fail "Data generation failed: $_"
    exit 1
}

# ── Step 4+5: Train models ────────────────────────────────────────────
Write-Step "Step 4/6: Prepare dataset + train ML models"
try {
    $TrainOut = python backend/ml/train.py --seed $Seed 2>&1
    $TrainOutput = $TrainOut -join "`n"
    # Parse selected model line
    $SelLine = ($TrainOut | Select-String "\[train\] Selected").Line
    Write-Success "Training complete. $SelLine"
    # Parse metrics
    ($TrainOut | Select-String "completion_time_s|energy_consumed_pct") | ForEach-Object {
        Write-Host "    $_" -ForegroundColor Gray
    }
} catch {
    Write-Fail "Training failed: $_"
    exit 1
}

# ── Step 6: Run benchmarks ────────────────────────────────────────────
Write-Step "Step 5/6: Run strategy comparison benchmarks"
try {
    $BenchOut = python backend/benchmarks/runner.py --scenarios $BenchScenarios --orders $BenchOrders --seed $Seed 2>&1
    $BenchOutput = $BenchOut -join "`n"
    # Show strategy comparison table
    ($BenchOut | Select-String "baseline|skygrid|ai_assist") | ForEach-Object {
        Write-Host "    $_" -ForegroundColor Yellow
    }
    Write-Success "Benchmarks complete. Results saved to results/"
} catch {
    Write-Fail "Benchmarks failed: $_"
    exit 1
}

# ── Step 7: Print result summary ──────────────────────────────────────
Write-Step "Step 6/6: Result summary"

if (Test-Path "results\ml_metrics.json") {
    $Metrics = Get-Content "results\ml_metrics.json" | ConvertFrom-Json
    $BestModel = $Metrics.selected_model
    $BestRMSE  = $Metrics.selected_model_val_rmse_avg
    Write-Host "  ML Model:          $BestModel (val_rmse_avg=$BestRMSE)" -ForegroundColor White
    $m = $Metrics.models.$BestModel
    if ($m) {
        Write-Host "  Time MAE (test):   $($m.test_completion_time_s_mae) s" -ForegroundColor White
        Write-Host "  Energy MAE (test): $($m.test_energy_consumed_pct_mae) %" -ForegroundColor White
        Write-Host "  Time R² (test):    $($m.test_completion_time_s_r2)" -ForegroundColor White
    }
}

if (Test-Path "results\benchmark_summary.csv") {
    Write-Host ""
    Write-Host "  Benchmark Strategy Comparison:" -ForegroundColor White
    Import-Csv "results\benchmark_summary.csv" | ForEach-Object {
        $rate = [math]::Round([double]$_.mean_delivery_rate * 100, 1)
        $energy = [math]::Round([double]$_.mean_energy_per_delivery, 2)
        $time = [math]::Round([double]$_.mean_completion_time_s, 0)
        Write-Host ("  {0,-14} delivery={1,5}%  energy/del={2,5}%  mean_time={3,4}s" -f $_.strategy, $rate, $energy, $time) -ForegroundColor White
    }
}

$Elapsed = (Get-Date) - $StartTime
Write-Host ""
Write-Host "══════════════════════════════════════════" -ForegroundColor Green
Write-Host "  🎉 Experiment complete in $([math]::Round($Elapsed.TotalSeconds))s" -ForegroundColor Green
Write-Host "  Docs:    docs/" -ForegroundColor Green
Write-Host "  Results: results/" -ForegroundColor Green
Write-Host "══════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
Write-Host "To start the live demo:" -ForegroundColor Cyan
Write-Host "  Terminal 1: cd backend; uvicorn main:app --host 0.0.0.0 --port 8000"
Write-Host "  Terminal 2: cd frontend; npm install; npm run dev"
Write-Host ""
