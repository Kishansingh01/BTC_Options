# Technical Walkthrough & Engineering Architecture Guide

This document provides a comprehensive, deeply technical walkthrough of the **BTC ATM Short Straddle** trading system implemented on **NautilusTrader** connected to **Bybit**.

It is structured to directly answer the **10 key architectural questions** outlined by the engineering team in Section 7 of the challenge specification.

---

## Architecture Overview

```
                      +---------------------------------------+
                      |       Bybit Exchange (WebSocket/REST) |
                      +---------------------------------------+
                                    ^               |
                    HTTP / WebSocket|               | Market Data & Fills
                     Orders & Claims|               v
                      +---------------------------------------+
                      |         Bybit Adapter (pyo3)          |
                      |  - BybitDataClient                    |
                      |  - BybitExecutionClient               |
                      +---------------------------------------+
                                    ^               |
                      Command Queue |               | Event Dispatch
                                    |               v
+-----------------------------------------------------------------------+
|                       NautilusTrader Core Engine                      |
|                                                                       |
|  +-------------------+   +--------------------+   +----------------+  |
|  |   LiveDataEngine  |   |   LiveExecEngine   |   |   LiveCache    |  |
|  +-------------------+   +--------------------+   +----------------+  |
|            |                       |                      |           |
|            +-----------+     +-----+                      |           |
|                        |     |                            |           |
|                        v     v                            v           |
|                 +---------------------------------------------+       |
|                 |       MessageBus (Asynchronous Bus)         |       |
|                 +---------------------------------------------+       |
|                                        |                              |
|                                        v                              |
|                 +---------------------------------------------+       |
|                 |         BTCShortStraddleStrategy            |       |
|                 |  1. ATM Strike Selection (selector.py)      |       |
|                 |  2. Leg Order Execution (Level 1)           |       |
|                 |  3. Ask-Side Buyback Valuation (Level 2)    |       |
|                 |  4. 1% Stop-Loss / 2% Take-Profit Logic     |       |
|                 |  5. Leg Desync & Duplicate Exit Guards      |       |
|                 +---------------------------------------------+       |
+-----------------------------------------------------------------------+
```

---

## Detailed Answers to the 10 Engineering Walkthrough Questions

### 1. How does NautilusTrader start and initialize?
* **Core Components:**
  - NautilusTrader initializes through a centralized orchestration container called `TradingNode` (configured via `TradingNodeConfig`).
  - Upon calling `node.build()`, the engine initializes its internal subsystems:
    1. **`LiveClock`**: High-resolution nanosecond clock for deterministic timestamping (`ts_event`, `ts_init`).
    2. **`MessageBus`**: Low-latency internal publish-subscribe message bus routing messages between adapters, engines, and strategies.
    3. **`LiveCache`**: In-memory state store tracking instruments, order books, working orders, trades, and position records.
    4. **`Portfolio`**: Aggregates balances, margin requirements, realized/unrealized PnL, and open positions per venue and account.
    5. **`LiveDataEngine`**: Manages market data feeds, subscriptions, and data distributor threads.
    6. **`LiveExecEngine`**: Manages order routing, client order ID generation, reconciliation, and flight tracking.
    7. **`Trader`**: Manages strategy lifecycles (`on_start()`, `on_stop()`, event distribution).
* **Strategy Attachment:**
  When `node.trader.add_strategy(strategy)` is called, the trader automatically calls `strategy.register(...)`, binding the strategy to the shared `PortfolioFacade`, `CacheFacade`, `MessageBus`, and `Clock`.
* **Startup Sequence:**
  Executing `node.run()` starts the asyncio event loop, connects the WebSocket/HTTP clients, reconciles open orders and positions from Bybit, and invokes `on_start()` on all registered strategies.

---

### 2. How have you configured the Bybit integration?
* **Configuration Classes:**
  We configure Bybit using NautilusTrader's native adapter classes: `BybitDataClientConfig` and `BybitExecClientConfig` in [live/run_live.py](file:///c:/Users/desktop/Downloads/BTC_Options/live/run_live.py).
* **Product Type Specification:**
  - For market data: We specify `product_types=(BybitProductType.Option, BybitProductType.Linear)` to load both the BTC Option chains and the linear perpetual/spot reference prices.
  - For execution: We specify `product_types=(BybitProductType.Option,)` since Bybit requires separate account margins (`MARGIN` account type) for derivative option trading.
* **Environment Multi-tenancy:**
  The system supports dynamic environment selection (`BybitEnvironment.Testnet`, `BybitEnvironment.Demo`, or `BybitEnvironment.Mainnet`) configured via `.env` or system environment variables.
* **Credentials:**
  API keys and HMAC-SHA256 secrets are injected via environment variables (`BYBIT_API_KEY` / `BYBIT_API_SECRET` or `BYBIT_TESTNET_API_KEY` / `BYBIT_TESTNET_API_SECRET`), keeping sensitive credentials isolated from codebase files.

---

### 3. How does NautilusTrader receive market data?
* **Network Layer:**
  - Fast async WebSocket client connecting to Bybit's public v5 market data endpoints (`wss://stream.bybit.com/v5/public/option` or testnet equivalent).
  - Background REST HTTP client (`BybitHttpClient`) for instrument definitions, reference specifications, and initial snapshot recovery.
* **Data Flow Pipeline:**
  1. WebSocket receives JSON payloads (e.g., `orderbook.50.BTC-...`, `tickers.BTC-...`).
  2. The Bybit Rust parser (`nautilus_pyo3.bybit`) deserializes the payload into high-performance zero-copy Cython data structures (`QuoteTick`, `OrderBookDelta`, `TradeTick`).
  3. The parsed data object is pushed onto the internal `MessageBus`.
  4. `LiveDataEngine` catches the event, updates the central `LiveCache`, and immediately notifies all strategies subscribed to that specific `InstrumentId`.

---

### 4. How are BTC option instruments identified and subscribed to?
* **Instrument Provider Discovery:**
  - At startup, `BybitInstrumentProvider` queries Bybit's `v5/market/instruments-info?category=option&baseCoin=BTC`.
  - NautilusTrader maps each contract into a `CryptoOption` instrument model containing:
    - Strike price (`strike_price: Price`)
    - Expiration UTC (`expiration_utc: datetime`)
    - Option Kind (`option_kind: OptionKind.CALL | OptionKind.PUT`)
    - Tick size and lot size (`price_increment`, `size_increment`, `lot_size`)
    - Native exchange symbol (e.g., `BTC-28MAR25-85000-C-USDT`) and canonical ID (`BTC-28MAR25-85000-C-USDT-OPTION.BYBIT`).
* **ATM Strike Selection Algorithm ([strategy/selector.py](file:///c:/Users/desktop/Downloads/BTC_Options/strategy/selector.py)):**
  1. Filters cached instruments where underlying is BTC (`is_btc_option()`).
  2. Groups available contracts by expiration timestamp.
  3. Identifies contracts that have **both** an active Call and Put at the identical strike and expiry.
  4. Takes the latest BTC underlying reference price (from `BTCUSDT-LINEAR.BYBIT` quote/trade).
  5. Computes $\min |K - P_{\text{ref}}|$ across all valid strikes $K$.
  6. Returns the paired `call_instrument` and `put_instrument`.
* **Subscription:**
  The strategy calls `self.subscribe_quote_ticks(call_instrument.id)` and `self.subscribe_quote_ticks(put_instrument.id)`.

---

### 5. How does the strategy receive market data events?
* **Event Dispatch:**
  When a quote tick matching a subscribed `InstrumentId` is received by the engine, the strategy's callback `on_quote_tick(self, tick: QuoteTick)` is triggered synchronously.
* **Separation of Concerns:**
  - If `tick.instrument_id == self.underlying_id`: Ticks are used to determine initial ATM strike selection.
  - If `tick.instrument_id == self.call_instrument.id`: Updates `self.latest_call_ask = float(tick.ask_price)` and evaluates risk management.
  - If `tick.instrument_id == self.put_instrument.id`: Updates `self.latest_put_ask = float(tick.ask_price)` and evaluates risk management.

---

### 6. How are orders submitted to Bybit?
* **Order Creation:**
  Orders are constructed using NautilusTrader's built-in `OrderFactory`:
  ```python
  call_order = self.order_factory.market(
      instrument_id=self.call_instrument.id,
      order_side=OrderSide.SELL,
      quantity=self.call_instrument.make_qty(self.config.contract_qty),
      time_in_force=TimeInForce.GTC,
  )
  ```
* **Order Submission:**
  The strategy invokes `self.submit_order(call_order)`.
* **Execution Engine Pipeline:**
  1. The `LiveExecEngine` receives the `SubmitOrder` command.
  2. Assigns a unique, venue-compliant `ClientOrderId` with routing tags.
  3. Checks local pre-trade risk controls (margin sufficiency, max notional, price sanity).
  4. Passes the command to `BybitExecutionClient`.
  5. The client serializes the payload, signs the request with HMAC-SHA256, and submits it to Bybit via WebSocket (`trade` stream) or REST API (`v5/order/create`).

---

### 7. How does the system know whether an order was accepted or executed?
NautilusTrader maintains an explicit **Order State Machine** driven by venue response events:
1. **`on_order_submitted(event: OrderSubmitted)`**:
   Confirmed that the order left the client application and is in flight to Bybit.
2. **`on_order_accepted(event: OrderAccepted)`**:
   Confirmed that Bybit received, validated, and placed the order into the exchange order book or matching engine. A `venue_order_id` is linked to our `client_order_id`.
3. **`on_order_rejected(event: OrderRejected)`**:
   If Bybit rejects the order (e.g. invalid margin, post-only cross, min size error), an `OrderRejected` event is published with the rejection reason.
4. **`on_order_filled(event: OrderFilled)`**:
   Published when an execution trade match occurs on Bybit. The event contains:
   - `last_px`: Execution price
   - `last_qty`: Filled quantity
   - `trade_id`: Unique exchange execution ID
   - `commission`: Incurred fee
   When `last_qty` matches total order quantity, the order status transitions to `FILLED`.

---

### 8. How are positions tracked?
* **Real-time Portfolio Integration:**
  - NautilusTrader tracks positions inside its Cython-optimized `Portfolio` subsystem.
  - Upon receiving `OrderFilled` events, `Portfolio` automatically creates or updates the corresponding `Position` object.
* **Lifecycle Events:**
  - **`on_position_opened(position: Position)`**: Triggered when a new net short position is established from flat (`FLAT -> SHORT`).
  - **`on_position_changed(position: Position)`**: Triggered on partial fills or position resizing, calculating volume-weighted average open price (`avg_px_open`).
  - **`on_position_closed(position: Position)`**: Triggered when net signed quantity returns to zero (`SHORT -> FLAT`).
* **Strategy State Cache:**
  The strategy maintains explicit tracking attributes:
  - `call_entry_price` & `put_entry_price`
  - `combined_entry_premium = call_entry_price + put_entry_price`
  - Contract quantities verified against `position.quantity`.

---

### 9. How have you implemented the Stop-Loss and Take-Profit?
* **Financial Specification:**
  - For a **Short Straddle**, the trader collects premium upfront.
  - To exit/close the short straddle, the trader must **buy back** both options:
    $$\text{Buyback Cost} = \text{Call Ask Price} + \text{Put Ask Price}$$
  - **Stop-Loss (1%)**: If the combined buyback premium increases by $\ge 1\%$ from entry, the strategy is losing money (costing more to buy back than collected).
    $$\text{SL Trigger} = \text{Combined Entry Premium} \times (1.0 + 0.01)$$
  - **Take-Profit (2%)**: If the combined buyback premium decreases by $\ge 2\%$ from entry, the strategy has gained profit from volatility/theta decay.
    $$\text{TP Trigger} = \text{Combined Entry Premium} \times (1.0 - 0.02)$$
* **Ask-Side Valuation:**
  In accordance with the challenge guidelines, buyback cost is computed strictly using the **ask price** (`tick.ask_price`), representing the real, actionable price required to lift liquidity and close short positions.
* **Duplicate Exit Prevention Guard:**
  To prevent race conditions where rapid quote updates trigger multiple closing orders before the first order confirms, the strategy uses an atomic state flag:
  ```python
  if self.is_exiting:
      return  # Early exit: closure already in flight
  self.is_exiting = True
  ```
* **Order Sizing & Reduce-Only:**
  When exiting, closing orders are submitted with `reduce_only=True` and sized strictly to the open position's quantity (`position.quantity`), preventing accidental position reversal into long exposure.

---

### 10. What happens when one leg gets executed but the other leg does not?
* **The Legging Risk Challenge:**
  In short straddle trading, executing one leg while the other fails leaves the book with naked directional exposure (e.g. short naked call with infinite upside risk, or short naked put with crash risk), defeating the market-neutral straddle structure.
* **Our Defensive Handling Architecture ([`_handle_leg_failure`]):**
  If one leg order is rejected, canceled, or fails to fill within `leg_timeout_secs`:
  1. **Immediate Partner Order Cancellation:**
     If the partner order is still pending/working on Bybit (`OrderStatus.SUBMITTED` or `OrderStatus.ACCEPTED`), the strategy immediately issues a `cancel_order(partner_order)` to abort entry.
  2. **Emergency Position Flattening:**
     If the partner leg has already been filled (or partially filled), the strategy detects that the straddle cannot be completed and immediately issues a market buy order with `reduce_only=True` to **flatten the filled leg**.
  3. **Alerting & Degradation:**
     Logs a high-priority warning detailing the leg desynchronization and transitions the strategy into a safe, dormant state.

---

## Verification & Testing Reference

Run the comprehensive test suite and scenario simulations locally:

```bash
# 1. Run all unit tests
pytest tests

# 2. Run Stop-Loss simulation
python backtest/run_simulation.py --scenario sl

# 3. Run Take-Profit simulation
python backtest/run_simulation.py --scenario tp

# 4. Preview live Bybit ATM contracts
python live/run_live.py --preview-only
```

