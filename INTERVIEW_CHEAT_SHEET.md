# Engineering Interview Quick-Reference Cheat Sheet

Use this cheat sheet during your walkthrough meeting with the trading systems engineering team. It provides high-impact, direct answers to the 10 questions from Section 7 of the challenge document.

---

### 1. How does NautilusTrader start and initialize?
* **Key Concept:** `TradingNode` lifecycle and asynchronous subsystems.
* **Talking Points:**
  - `TradingNode` is configured via `TradingNodeConfig`.
  - When calling `node.build()`, it initializes the core subsystems:
    1. **`LiveClock`**: Nanosecond-resolution timestamping engine.
    2. **`MessageBus`**: Low-latency internal publish-subscribe message bus.
    3. **`LiveCache`**: In-memory state store for instruments, order books, and orders.
    4. **`Portfolio`**: Account balances, margins, and open positions tracker.
    5. **`LiveDataEngine` & `LiveExecEngine`**: Ingestion and execution routers.
  - Calling `node.trader.add_strategy(strategy)` registers the strategy with all internal facades.
  - Calling `node.run()` starts the asyncio event loop, connects exchange WebSockets, reconciles state, and invokes `on_start()`.

---

### 2. How have you configured the Bybit integration?
* **Key Concept:** Separation of data vs derivative execution clients.
* **Talking Points:**
  - Used native `BybitDataClientConfig` and `BybitExecClientConfig`.
  - Configured `product_types=(BybitProductType.Option, BybitProductType.Linear)` on data client to stream both option chains and underlying perpetual prices.
  - Execution client is configured with `product_types=(BybitProductType.Option,)` using Bybit's derivative margin account model.
  - Multi-environment switching (`Testnet`, `Demo`, `Mainnet`) via `.env`.

---

### 3. How does NautilusTrader receive market data?
* **Key Concept:** WebSocket streaming + zero-copy PyO3/Cython parsing.
* **Talking Points:**
  - Connects to Bybit's v5 WebSocket endpoints (`wss://stream.bybit.com/v5/public/option`).
  - Low-level Rust adapter (`nautilus_pyo3.bybit`) parses JSON payloads directly into Cython data types (`QuoteTick`, `TradeTick`).
  - Ticks are pushed through the `MessageBus` to `LiveDataEngine`, cache is updated, and dispatched to `on_quote_tick()`.

---

### 4. How are BTC option instruments identified and subscribed to?
* **Key Concept:** `BybitInstrumentProvider` discovery + dynamic ATM matching.
* **Talking Points:**
  - `BybitInstrumentProvider` loads all active instruments via Bybit REST endpoint (`v5/market/instruments-info?category=option&baseCoin=BTC`).
  - NautilusTrader maps them into typed `CryptoOption` models (containing `strike_price`, `expiration_utc`, `option_kind`, lot size, tick size).
  - Our [`find_atm_straddle_pair()`](file:///c:/Users/desktop/Downloads/BTC_Options/strategy/selector.py) algorithm:
    1. Groups options by expiration date.
    2. Keeps only strikes with **both** an active Call and Put.
    3. Minimizes $|K - P_{\text{ref}}|$ against the live BTC reference price.
  - The strategy calls `self.subscribe_quote_ticks(call_instrument.id)` and `self.subscribe_quote_ticks(put_instrument.id)`.

---

### 5. How does the strategy receive market data events?
* **Key Concept:** Strongly typed event-driven callbacks.
* **Talking Points:**
  - When the engine processes a tick for a subscribed `InstrumentId`, it calls `on_quote_tick(self, tick: QuoteTick)`.
  - Underlying ticks update reference price and trigger straddle selection.
  - Option ticks update `self.latest_call_ask` and `self.latest_put_ask`, triggering real-time risk checks.

---

### 6. How are orders submitted to Bybit?
* **Key Concept:** `OrderFactory` + `LiveExecEngine` signing and routing.
* **Talking Points:**
  - Orders are created via `self.order_factory.market(instrument_id, OrderSide.SELL, quantity, time_in_force=TimeInForce.GTC)`.
  - `self.submit_order(order)` dispatches a `SubmitOrder` command to `LiveExecEngine`.
  - Engine validates risk parameters, assigns a unique `ClientOrderId`, signs the payload via HMAC-SHA256, and sends it to Bybit over the private trade WebSocket / REST endpoint.

---

### 7. How does the system know whether an order was accepted or executed?
* **Key Concept:** NautilusTrader Order State Machine.
* **Talking Points:**
  - **`on_order_submitted`**: Sent over the wire.
  - **`on_order_accepted`**: Bybit confirmed receipt and assigned `venue_order_id`.
  - **`on_order_rejected`**: Bybit rejected order (margin, invalid strike, etc.).
  - **`on_order_filled`**: Exchange matching engine executed trade. Contains `last_px`, `last_qty`, `trade_id`, and commission fees. Order status moves to `FILLED`.

---

### 8. How are positions tracked?
* **Key Concept:** `Portfolio` subsystem integration.
* **Talking Points:**
  - Fills automatically update NautilusTrader's `Portfolio` and `Position` objects.
  - Lifecycle events dispatched: `on_position_opened`, `on_position_changed` (VWAP avg price recalculation), `on_position_closed`.
  - Strategy stores `combined_entry_premium = call_entry_price + put_entry_price` to establish exact baseline for risk management.

---

### 9. How have you implemented Stop-Loss and Take-Profit?
* **Key Concept:** Ask-side buyback valuation + atomic exit guard.
* **Talking Points:**
  - To exit a short straddle, we must **buy back** both legs:
    $$\text{Buyback Cost} = \text{Call Ask Price} + \text{Put Ask Price}$$
  - **Stop-Loss (1%)**: If buyback cost increases by $\ge 1\%$ (`current_buyback >= entry * 1.01`), we exit.
  - **Take-Profit (2%)**: If buyback cost decreases by $\ge 2\%$ (`current_buyback <= entry * 0.98`), we exit.
  - **Duplicate Exit Guard**: Atomic boolean flag `if self.is_exiting: return` prevents duplicate market orders when rapid quotes arrive.
  - **Order Sizing**: Submits market buy orders for `position.quantity` with `reduce_only=True` to guarantee we never flip to a long position.

---

### 10. What happens when one leg gets executed but the other leg does not?
* **Key Concept:** Legging risk mitigation & defensive flattening.
* **Talking Points:**
  - If leg 1 fills but leg 2 is rejected, canceled, or fails to fill within timeout:
    1. **Cancel Partner Order**: Immediately cancel working order for the unfilled leg.
    2. **Flatten Filled Leg**: Submit an immediate closing market order with `reduce_only=True` for the filled leg.
  - **Rationale**: An unhedged single leg carries unbounded directional delta risk, which violates the delta-neutral structure of a short straddle.

