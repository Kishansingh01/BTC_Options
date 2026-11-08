# NautilusTrader BTC Options Short Straddle Trading System

Production-ready implementation of an automated **BTC At-The-Money (ATM) Short Straddle Strategy** on **NautilusTrader**, connected to **Bybit**.

Developed for the NautilusTrader Bybit Options Engineering Challenge.

---

## Features

### Level 1 – Naked Straddle (Core)
- **Bybit Integration**: Configured for Bybit options and linear derivatives across Testnet, Demo, and Mainnet.
- **Dynamic ATM Strike Selection**: Automatically discovers live BTC options chains, finds matching Call and Put pairs with identical strike and expiry, and selects the nearest strike to the BTC reference price.
- **Order Execution & Tracking**: Submits sell orders for both legs and tracks order states (`SUBMITTED`, `ACCEPTED`, `FILLED`, `REJECTED`, `CANCELED`).
- **Real-Time Position Tracking**: Monitors open position sizes, average entry prices, and combined entry premium.

### Level 2 – Automated Risk Management (Advanced)
- **Ask-Side Buyback Valuation**: Continuously monitors ask prices for both option legs to calculate true liquidation / buyback cost.
- **Automated Stop-Loss (1%)**: Automatically triggers market buyback orders when the combined buyback premium increases by $\ge 1\%$ from entry.
- **Automated Take-Profit (2%)**: Automatically triggers market buyback orders when the combined buyback premium decreases by $\ge 2\%$ from entry.
- **Duplicate Exit Prevention**: Thread-safe atomic exit state protection preventing duplicate closing orders during rapid market ticks.
- **Leg Desynchronization & Asymmetric Fill Protection**: Automatically cancels working partner orders and flattens filled legs if one leg fails or gets rejected.

---

## Directory Structure

```
BTC_Options/
├── README.md                      # Project documentation and quickstart
├── WALKTHROUGH.md                 # Detailed walkthrough answering the 10 engineering questions
├── requirements.txt               # Dependencies
├── .env.example                   # Environment variable template
├── config.py                      # Environment and configuration loader
├── strategy/
│   ├── __init__.py
│   ├── selector.py                # Strike selection & contract pairing logic
│   └── straddle.py                # BTCShortStraddleStrategy (Level 1 & Level 2)
├── live/
│   ├── __init__.py
│   └── run_live.py                # TradingNode runner for live/testnet execution
├── backtest/
│   ├── __init__.py
│   └── run_simulation.py          # Standalone event-driven simulation runner
└── tests/
    ├── __init__.py
    ├── helpers.py                 # Synthetic instrument and event generators
    ├── test_atm_selection.py      # Unit tests for ATM strike matching
    └── test_risk_management.py    # Unit tests for SL/TP and edge case handling
```

---

## Quickstart Guide

### 1. Installation
Ensure Python 3.11 or 3.12 is active, then install dependencies:
```bash
pip install -r requirements.txt
```

### 2. Run the Automated Unit Tests
Verify all 9 tests covering strike selection, risk management, SL/TP triggers, and duplicate exit handling:
```bash
pytest tests
```

### 3. Run the Strategy Simulation
Simulate the full order execution and risk management lifecycle:

- **Stop-Loss scenario** (simulates premium expansion triggering +1% exit):
  ```bash
  python backtest/run_simulation.py --scenario sl
  ```

- **Take-Profit scenario** (simulates premium decay triggering -2% exit):
  ```bash
  python backtest/run_simulation.py --scenario tp
  ```

- **Level 1 Naked Straddle scenario** (runs without SL/TP):
  ```bash
  python backtest/run_simulation.py --level 1 --scenario neutral
  ```

---

## Live & Testnet Execution

### 1. Environment Setup
Copy `.env.example` to `.env` and fill in your Bybit API credentials:
```bash
cp .env.example .env
```
Key configuration settings in `.env`:
```env
BYBIT_API_KEY=your_bybit_api_key
BYBIT_API_SECRET=your_bybit_api_secret
BYBIT_ENVIRONMENT=TESTNET  # TESTNET, DEMO, or MAINNET
CONTRACT_QTY=0.01
USE_RISK_MANAGEMENT=true
STOP_LOSS_PCT=0.01
TAKE_PROFIT_PCT=0.02
```

### 2. Preview Live Bybit ATM Options
To test your connection to Bybit and inspect currently available BTC options chains without placing orders:
```bash
python live/run_live.py --preview-only
```

### 3. Start the Live Strategy Node
To start the live trading node with real-time Bybit WebSocket and REST connections:
```bash
python live/run_live.py
```
To run Level 1 mode (naked straddle):
```bash
python live/run_live.py --level1
```

---

## Technical Walkthrough Guide
For the full engineering discussion and answers to the **10 technical questions** from Section 7 of the challenge document, please refer to:
[WALKTHROUGH.md](file:///c:/Users/desktop/Downloads/BTC_Options/WALKTHROUGH.md)

