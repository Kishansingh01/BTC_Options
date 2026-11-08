from __future__ import annotations

import sys
import time

QUESTIONS = [
    {
        "num": 1,
        "title": "How does NautilusTrader start and initialize?",
        "summary": "Centralized TradingNode orchestration with asynchronous actors.",
        "details": """
- The orchestration container is TradingNode (configured via TradingNodeConfig).
- When node.build() is invoked, it instantiates:
    1. LiveClock: High-resolution nanosecond clock (ts_event, ts_init).
    2. MessageBus: Lock-free asynchronous publish-subscribe message bus.
    3. LiveCache: In-memory state store for instruments, order books, and orders.
    4. Portfolio: Central balance, margin, and position aggregator.
    5. LiveDataEngine & LiveExecEngine: Ingestion and routing engines.
- Calling node.trader.add_strategy(strategy) binds the strategy to all shared facades.
- Calling node.run() starts the event loop, connects exchange sockets, reconciles state, and invokes on_start().
        """,
    },
    {
        "num": 2,
        "title": "How have you configured the Bybit integration?",
        "summary": "Dual client configuration: Multi-asset data client + Derivative margin execution client.",
        "details": """
- Data Client (BybitDataClientConfig):
    - Configured with product_types=(BybitProductType.Option, BybitProductType.Linear).
    - This streams both BTC Option chains and linear perpetual prices (BTCUSDT) for reference pricing.
- Execution Client (BybitExecClientConfig):
    - Configured with product_types=(BybitProductType.Option,).
    - Bybit enforces separate derivative margin accounts for options trading.
- Multi-environment flexibility:
    - Sourced from .env via BYBIT_ENVIRONMENT (Testnet, Demo, Mainnet) and API keys.
        """,
    },
    {
        "num": 3,
        "title": "How does NautilusTrader receive market data?",
        "summary": "Async WebSocket streams + Zero-copy PyO3/Rust deserialization into Cython types.",
        "details": """
- Connects to Bybit's v5 WebSocket endpoints (wss://stream.bybit.com/v5/public/option).
- Bybit's Rust adapter (nautilus_pyo3.bybit) deserializes JSON directly into typed Cython objects (QuoteTick, TradeTick).
- Data is published to the internal MessageBus.
- LiveDataEngine updates the LiveCache and synchronously dispatches to the strategy's on_quote_tick() callback.
        """,
    },
    {
        "num": 4,
        "title": "How are BTC option instruments identified and subscribed to?",
        "summary": "BybitInstrumentProvider discovery + dynamic ATM strike pairing algorithm.",
        "details": """
- BybitInstrumentProvider fetches active option instruments via Bybit REST API.
- Parsed into CryptoOption objects (with strike_price, expiration_utc, option_kind).
- find_atm_straddle_pair() algorithm:
    1. Filters instruments where underlying is BTC.
    2. Groups contracts by expiration date.
    3. Identifies strikes that have BOTH a Call and a Put.
    4. Minimizes |K - P_ref| relative to the live BTC reference price.
- Strategy subscribes to quotes: self.subscribe_quote_ticks(call_id) & self.subscribe_quote_ticks(put_id).
        """,
    },
    {
        "num": 5,
        "title": "How does the strategy receive market data events?",
        "summary": "Strategy on_quote_tick() lifecycle callback dispatched via MessageBus.",
        "details": """
- Dispatched directly into on_quote_tick(self, tick: QuoteTick).
- Filtered by InstrumentId:
    - If underlying_id: updates reference price and selects ATM strike.
    - If call_instrument.id: updates self.latest_call_ask and evaluates risk.
    - If put_instrument.id: updates self.latest_put_ask and evaluates risk.
        """,
    },
    {
        "num": 6,
        "title": "How are orders submitted to Bybit?",
        "summary": "OrderFactory construction -> LiveExecEngine routing -> HMAC-signed WebSocket/REST transmission.",
        "details": """
- Orders created via self.order_factory.market(instrument_id, OrderSide.SELL, quantity, time_in_force=TimeInForce.GTC).
- Strategy calls self.submit_order(order), which dispatches SubmitOrder to LiveExecEngine.
- LiveExecEngine validates pre-trade risk, assigns unique ClientOrderId, signs payload with HMAC-SHA256, and submits over Bybit trade WebSocket / REST.
        """,
    },
    {
        "num": 7,
        "title": "How does the system know whether an order was accepted or executed?",
        "summary": "Event-driven Order State Machine transitions.",
        "details": """
- on_order_submitted: Outbound flight confirmed.
- on_order_accepted: Bybit validated and registered order in exchange matching engine (venue_order_id linked).
- on_order_rejected: Bybit rejected (margin, price out of bounds, etc.).
- on_order_filled: Trade executed. Contains last_px, last_qty, trade_id, and commission. Transitions order to FILLED.
        """,
    },
    {
        "num": 8,
        "title": "How are positions tracked?",
        "summary": "Portfolio subsystem position records + Strategy entry premium baseline cache.",
        "details": """
- OrderFilled events automatically update NautilusTrader's Portfolio.
- Dispatches on_position_opened, on_position_changed (VWAP recalculation), and on_position_closed.
- Strategy records call_entry_price, put_entry_price, and combined_entry_premium = call_entry_price + put_entry_price.
        """,
    },
    {
        "num": 9,
        "title": "How have you implemented Stop-Loss and Take-Profit?",
        "summary": "Ask-side buyback cost valuation + 1% SL / 2% TP thresholds + atomic exit guard.",
        "details": """
- Buyback Valuation:
    Buyback Cost = Call Ask Price + Put Ask Price (uses ask quotes because buying back lifts liquidity).
- Stop-Loss (1%):
    Triggers when buyback cost >= combined_entry_premium * 1.01.
- Take-Profit (2%):
    Triggers when buyback cost <= combined_entry_premium * 0.98.
- Duplicate Exit Guard:
    Atomic flag (if self.is_exiting: return; self.is_exiting = True) prevents duplicate market orders.
- Order Sizing:
    Submits market BUY orders for exact open quantity with reduce_only=True.
        """,
    },
    {
        "num": 10,
        "title": "What happens when one leg gets executed but the other leg does not?",
        "summary": "Defensive legging-risk mitigation: cancel unfilled partner order and flatten filled position.",
        "details": """
- Danger: An unhedged single short option carries unlimited directional delta risk.
- Mitigation (_handle_leg_failure):
    1. If partner order is working: immediately calls self.cancel_order(partner_order).
    2. If partner position is already open: immediately submits market closing order with reduce_only=True to flatten.
    3. Logs a high-priority alert and transitions strategy into safe completed state.
        """,
    },
]


def run_interactive_interview():
    print("=" * 75)
    print("NAUTILUSTRADER BTC OPTIONS STRADDLE: MOCK INTERVIEW SIMULATOR")
    print("=" * 75)
    print("Practice answering the 10 engineering questions from the assignment.")
    print("Press [ENTER] to reveal the ideal technical answer for each question.\n")

    for item in QUESTIONS:
        print("-" * 75)
        print(f"QUESTION {item['num']}/10: {item['title']}")
        print(f"Core Focus: {item['summary']}")
        print("-" * 75)
        input(">> Press [ENTER] to see the comprehensive engineering answer...")
        print(item["details"].strip())
        print()

    print("=" * 75)
    print("ALL 10 INTERVIEW QUESTIONS REVIEWED!")
    print("Review WALKTHROUGH.md and INTERVIEW_CHEAT_SHEET.md for offline study.")
    print("=" * 75)


if __name__ == "__main__":
    run_interactive_interview()
