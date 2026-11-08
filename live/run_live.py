from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from decimal import Decimal

from nautilus_trader.adapters.bybit import (
    BybitDataClientConfig,
    BybitEnvironment,
    BybitExecClientConfig,
    BybitLiveDataClientFactory,
    BybitLiveExecClientFactory,
    BybitProductType,
    get_cached_bybit_http_client,
    get_cached_bybit_instrument_provider,
)
from nautilus_trader.live.config import LiveExecEngineConfig, TradingNodeConfig
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.identifiers import TraderId

from config import get_bybit_api_credentials, get_bybit_environment, get_trading_config_dict
from strategy.selector import find_atm_straddle_pair
from strategy.straddle import BTCShortStraddleConfig, BTCShortStraddleStrategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("BybitStraddleRunner")


def build_node(
    environment: BybitEnvironment,
    api_key: str | None,
    api_secret: str | None,
    trading_cfg: dict,
    is_live_execution: bool = True,
) -> TradingNode:
    """
    Build and configure the NautilusTrader TradingNode for Bybit options trading.
    """
    # 1. Bybit Live Data Client Configuration
    data_client_config = BybitDataClientConfig(
        api_key=api_key,
        api_secret=api_secret,
        environment=environment,
        product_types=(
            BybitProductType.from_str("Option"),
            BybitProductType.from_str("Linear"),
        ),
        instrument_status_poll_secs=60,
    )

    data_clients = {"BYBIT": data_client_config}
    exec_clients = {}

    # 2. Bybit Execution Client Configuration (if executing live orders)
    if is_live_execution and api_key and api_secret:
        exec_client_config = BybitExecClientConfig(
            api_key=api_key,
            api_secret=api_secret,
            environment=environment,
            product_types=(BybitProductType.from_str("Option"),),
        )
        exec_clients["BYBIT"] = exec_client_config

    node_config = TradingNodeConfig(
        trader_id=TraderId("TRADER-001"),
        exec_engine=LiveExecEngineConfig(reconciliation=True),
        data_clients=data_clients,
        exec_clients=exec_clients,
    )

    node = TradingNode(config=node_config)

    # Register factories
    node.add_data_client_factory("BYBIT", BybitLiveDataClientFactory)
    if exec_clients:
        node.add_exec_client_factory("BYBIT", BybitLiveExecClientFactory)

    # Build node infrastructure
    node.build()

    # Configure Strategy
    strat_config = BTCShortStraddleConfig(
        underlying_instrument_id="BTCUSDT-LINEAR.BYBIT",
        contract_qty=trading_cfg["contract_qty"],
        use_risk_management=trading_cfg["use_risk_management"],
        stop_loss_pct=trading_cfg["stop_loss_pct"],
        take_profit_pct=trading_cfg["take_profit_pct"],
    )
    strategy = BTCShortStraddleStrategy(config=strat_config)
    node.trader.add_strategy(strategy)

    return node


async def fetch_and_preview_atm(environment: BybitEnvironment):
    """
    Utility function to query Bybit, load live instruments, and display the current ATM straddle.
    """
    logger.info("Connecting to Bybit HTTP to inspect available BTC options...")
    client = get_cached_bybit_http_client(
        api_key=None,
        api_secret=None,
        environment=environment,
    )
    provider = get_cached_bybit_instrument_provider(
        client=client,
        product_types=(BybitProductType.from_str("Option"), BybitProductType.from_str("Linear")),
    )
    await provider.load_all_async()
    instruments = provider.list_all()

    btc_options = [inst for inst in instruments if "BTC" in inst.id.value and ("-C" in inst.id.value or "-P" in inst.id.value)]
    logger.info(f"Loaded {len(btc_options)} BTC options from Bybit.")

    # Approximate BTC reference price from linear perpetual or default
    reference_price = 85000.0  # approximate reference
    pair = find_atm_straddle_pair(instruments, reference_price=reference_price)
    if pair:
        call_inst, put_inst, strike, expiry = pair
        print("\n" + "=" * 70)
        print("LIVE BYBIT ATM STRADDLE PREVIEW:")
        print(f"  Reference Price: {reference_price}")
        print(f"  ATM Strike: {strike}")
        print(f"  Expiry: {expiry}")
        print(f"  Call Contract: {call_inst.id.value}")
        print(f"  Put Contract:  {put_inst.id.value}")
        print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Bybit BTC Options Short Straddle Runner")
    parser.add_argument("--preview-only", action="store_true", help="Fetch and preview available ATM options without running node")
    parser.add_argument("--level1", action="store_true", help="Run Level 1 naked straddle (disable SL/TP risk management)")
    args = parser.parse_args()

    env = get_bybit_environment()
    api_key, api_secret = get_bybit_api_credentials()
    trading_cfg = get_trading_config_dict()

    if args.level1:
        trading_cfg["use_risk_management"] = False

    logger.info(f"Using Bybit Environment: {env}")
    logger.info(f"Risk Management: {'Active (Level 2)' if trading_cfg['use_risk_management'] else 'Disabled (Level 1)'}")

    if args.preview_only:
        asyncio.run(fetch_and_preview_atm(env))
        return

    node = build_node(
        environment=env,
        api_key=api_key,
        api_secret=api_secret,
        trading_cfg=trading_cfg,
        is_live_execution=bool(api_key and api_secret),
    )

    logger.info("Starting TradingNode...")
    try:
        node.run()
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user.")
    finally:
        node.stop()
        node.dispose()


if __name__ == "__main__":
    main()

