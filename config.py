from __future__ import annotations

import os
from decimal import Decimal
from dotenv import load_dotenv
from nautilus_trader.adapters.bybit import BybitEnvironment

# Load .env if present
load_dotenv()


def get_bybit_environment() -> BybitEnvironment:
    env_str = os.getenv("BYBIT_ENVIRONMENT", "TESTNET").strip().upper()
    if env_str == "MAINNET":
        return BybitEnvironment.from_str("Mainnet")
    elif env_str == "DEMO":
        return BybitEnvironment.from_str("Demo")
    else:
        return BybitEnvironment.from_str("Testnet")


def get_bybit_api_credentials() -> tuple[str | None, str | None]:
    api_key = os.getenv("BYBIT_API_KEY") or os.getenv("BYBIT_TESTNET_API_KEY")
    api_secret = os.getenv("BYBIT_API_SECRET") or os.getenv("BYBIT_TESTNET_API_SECRET")
    return api_key, api_secret


def get_trading_config_dict() -> dict:
    return {
        "underlying_symbol": os.getenv("UNDERLYING_SYMBOL", "BTCUSDT"),
        "contract_qty": Decimal(os.getenv("CONTRACT_QTY", "0.01")),
        "use_risk_management": os.getenv("USE_RISK_MANAGEMENT", "true").lower() in ("1", "true", "yes"),
        "stop_loss_pct": float(os.getenv("STOP_LOSS_PCT", "0.01")),
        "take_profit_pct": float(os.getenv("TAKE_PROFIT_PCT", "0.02")),
    }

