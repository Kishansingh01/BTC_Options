param(
    [Parameter(Position=0)]
    [ValidateSet("test", "sl", "tp", "level1", "preview", "live", "interview", "chart")]
    [string]$Command = "test"
)

$env:PYTHONPATH = "."

switch ($Command) {
    "test" {
        Write-Host "Running unit test suite..." -ForegroundColor Cyan
        pytest tests -v
    }
    "sl" {
        Write-Host "Running Stop-Loss (+1% buyback expansion) simulation..." -ForegroundColor Yellow
        python backtest/run_simulation.py --scenario sl
    }
    "tp" {
        Write-Host "Running Take-Profit (-2% theta/vol decay) simulation..." -ForegroundColor Green
        python backtest/run_simulation.py --scenario tp
    }
    "level1" {
        Write-Host "Running Level 1 Naked Straddle simulation..." -ForegroundColor Cyan
        python backtest/run_simulation.py --level 1 --scenario neutral
    }
    "preview" {
        Write-Host "Connecting to live Bybit API to preview current ATM contracts..." -ForegroundColor Magenta
        python live/run_live.py --preview-only
    }
    "chart" {
        Write-Host "Generating payoff chart and Greeks analysis..." -ForegroundColor Green
        python strategy/analytics.py
    }
    "interview" {
        Write-Host "Launching Mock Interview Simulator..." -ForegroundColor Yellow
        python interview_sim.py
    }
    "live" {
        Write-Host "Starting NautilusTrader live node..." -ForegroundColor Magenta
        python live/run_live.py
    }
}

