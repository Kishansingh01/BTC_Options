from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.model.data import QuoteTick, TradeTick
from nautilus_trader.model.enums import (
    OrderSide,
    OrderStatus,
    TimeInForce,
)
from nautilus_trader.model.events import (
    OrderAccepted,
    OrderCanceled,
    OrderFilled,
    OrderRejected,
    OrderSubmitted,
    PositionChanged,
    PositionClosed,
    PositionOpened,
)
from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Quantity
from nautilus_trader.model.position import Position
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy

from strategy.selector import find_atm_straddle_pair

logger = logging.getLogger(__name__)


def calculate_stop_loss_price(combined_entry_premium: float, stop_loss_pct: float = 0.01) -> float:
    """
    Calculate the Stop-Loss buyback premium threshold.
    For short straddles, paying more premium to buy back represents a loss.
    SL triggers when current buyback >= entry * (1 + stop_loss_pct).
    """
    return combined_entry_premium * (1.0 + stop_loss_pct)


def calculate_take_profit_price(combined_entry_premium: float, take_profit_pct: float = 0.02) -> float:
    """
    Calculate the Take-Profit buyback premium threshold.
    For short straddles, paying less premium to buy back represents a profit.
    TP triggers when current buyback <= entry * (1 - take_profit_pct).
    """
    return combined_entry_premium * (1.0 - take_profit_pct)


def evaluate_exit_signal(
    current_buyback_premium: float,
    stop_loss_trigger: float,
    take_profit_trigger: float,
) -> str | None:
    """
    Determine if an exit signal (STOP-LOSS or TAKE-PROFIT) is triggered.
    """
    if current_buyback_premium >= stop_loss_trigger:
        return "STOP-LOSS"
    if current_buyback_premium <= take_profit_trigger:
        return "TAKE-PROFIT"
    return None


class BTCShortStraddleConfig(StrategyConfig, frozen=True):
    """
    Configuration for the BTC ATM Short Straddle Strategy.

    Parameters
    ----------
    underlying_instrument_id : str
        The instrument ID of the BTC underlying reference (e.g. 'BTCUSDT-LINEAR.BYBIT' or 'BTCUSDT.BYBIT').
    contract_qty : Decimal, default 0.01
        The order quantity for each leg of the straddle (Bybit minimum BTC option lot is 0.01).
    target_expiry : str | None, optional
        Target expiry string (e.g. '28MAR25') or None to select the nearest available expiry.
    use_risk_management : bool, default True
        Level 1 vs Level 2 toggle:
        - False: Naked Straddle (no SL, no TP).
        - True: Automated Risk Management (SL & TP active).
    stop_loss_pct : float, default 0.01
        Stop-loss threshold: 1% increase in combined buyback premium from entry.
    take_profit_pct : float, default 0.02
        Take-profit threshold: 2% decrease in combined buyback premium from entry.
    reference_price_override : float | None, optional
        Direct reference price override (useful for testing or simulation).
    leg_timeout_secs : float, default 30.0
        Timeout for both legs to achieve initial fill before triggering mismatched leg protection.
    """

    underlying_instrument_id: str = "BTCUSDT-LINEAR.BYBIT"
    contract_qty: Decimal = Decimal("0.01")
    target_expiry: Optional[str] = None
    use_risk_management: bool = True
    stop_loss_pct: float = 0.01
    take_profit_pct: float = 0.02
    reference_price_override: Optional[float] = None
    leg_timeout_secs: float = 30.0


class BTCShortStraddleStrategy(Strategy):
    """
    BTC ATM Short Straddle Strategy for NautilusTrader.

    Implements:
    - Level 1: Naked Short Straddle (ATM Call + ATM Put selling, position tracking).
    - Level 2: Automated Risk Management (1% Stop-Loss, 2% Take-Profit evaluated
      using combined ask-side buyback quotes).
    - Leg desynchronization protection and duplicate exit prevention.
    """

    def __init__(self, config: BTCShortStraddleConfig) -> None:
        super().__init__(config)

        self.underlying_id: InstrumentId = InstrumentId.from_str(config.underlying_instrument_id)
        self.call_instrument: Optional[Instrument] = None
        self.put_instrument: Optional[Instrument] = None
        self.strike_price: Optional[float] = None
        self.expiry = None

        # Order tracking
        self.call_order_id: Optional[ClientOrderId] = None
        self.put_order_id: Optional[ClientOrderId] = None
        self.call_filled_qty: Decimal = Decimal("0")
        self.put_filled_qty: Decimal = Decimal("0")
        self.call_entry_price: Optional[float] = None
        self.put_entry_price: Optional[float] = None
        self.combined_entry_premium: Optional[float] = None

        # Level 2 Risk thresholds
        self.stop_loss_trigger_price: Optional[float] = None
        self.take_profit_trigger_price: Optional[float] = None

        # Real-time ask quotes for buyback valuation
        self.latest_call_ask: Optional[float] = None
        self.latest_put_ask: Optional[float] = None

        # State flags
        self.reference_price_received: bool = False
        self.straddle_initialized: bool = False
        self.straddle_entered: bool = False
        self.is_exiting: bool = False
        self.is_closed: bool = False

    def on_start(self) -> None:
        """
        Called when the strategy is started.
        """
        self.log.info(
            f"BTCShortStraddleStrategy started | "
            f"Underlying: {self.underlying_id.value} | "
            f"Risk Management: {'ENABLED' if self.config.use_risk_management else 'DISABLED (Level 1)'}"
        )

        # If a reference price override is provided, immediately initialize the straddle
        if self.config.reference_price_override is not None:
            self.log.info(f"Using reference price override: {self.config.reference_price_override}")
            self._select_and_enter_straddle(self.config.reference_price_override)
            return

        # Otherwise subscribe to underlying reference ticks
        self.subscribe_quote_ticks(self.underlying_id)
        self.subscribe_trade_ticks(self.underlying_id)

    def on_quote_tick(self, tick: QuoteTick) -> None:
        """
        Handle incoming QuoteTick events.
        """
        # 1. Underlying price update for ATM selection
        if not self.straddle_initialized and tick.instrument_id == self.underlying_id:
            ref_price = float((tick.bid_price + tick.ask_price) / 2)
            self.log.info(f"Received underlying quote: Bid={tick.bid_price}, Ask={tick.ask_price} -> Mid={ref_price:.2f}")
            self._select_and_enter_straddle(ref_price)
            return

        # 2. Straddle leg quote ticks for buyback valuation
        if self.call_instrument and tick.instrument_id == self.call_instrument.id:
            self.latest_call_ask = float(tick.ask_price)
            self._evaluate_risk_management()

        elif self.put_instrument and tick.instrument_id == self.put_instrument.id:
            self.latest_put_ask = float(tick.ask_price)
            self._evaluate_risk_management()

    def on_trade_tick(self, tick: TradeTick) -> None:
        """
        Handle incoming TradeTick events.
        """
        if not self.straddle_initialized and tick.instrument_id == self.underlying_id:
            ref_price = float(tick.price)
            self.log.info(f"Received underlying trade price: {ref_price:.2f}")
            self._select_and_enter_straddle(ref_price)

    def _select_and_enter_straddle(self, reference_price: float) -> None:
        """
        Select ATM Call and Put instruments and submit sell orders.
        """
        if self.straddle_initialized:
            return

        self.straddle_initialized = True
        instruments = self.cache.instruments()
        self.log.info(f"Total instruments in cache: {len(instruments)}")

        pair = find_atm_straddle_pair(
            instruments=instruments,
            reference_price=reference_price,
            target_expiry=self.config.target_expiry,
        )

        if pair is None:
            self.log.error(f"Could not find matching ATM straddle pair for ref price {reference_price:.2f}")
            return

        self.call_instrument, self.put_instrument, self.strike_price, self.expiry = pair
        self.log.info(
            f"ATM Straddle selected: Strike={self.strike_price}, Expiry={self.expiry}\n"
            f"  Call: {self.call_instrument.id.value}\n"
            f"  Put:  {self.put_instrument.id.value}"
        )

        # Subscribe to market data for both option legs
        self.subscribe_quote_ticks(self.call_instrument.id)
        self.subscribe_quote_ticks(self.put_instrument.id)

        # Submit short orders for both legs
        self._submit_entry_orders()

    def _submit_entry_orders(self) -> None:
        """
        Submit SELL orders for Call and Put options.
        """
        qty = self.call_instrument.make_qty(self.config.contract_qty)

        # Create Market SELL orders
        call_order = self.order_factory.market(
            instrument_id=self.call_instrument.id,
            order_side=OrderSide.SELL,
            quantity=qty,
            time_in_force=TimeInForce.GTC,
        )
        put_order = self.order_factory.market(
            instrument_id=self.put_instrument.id,
            order_side=OrderSide.SELL,
            quantity=qty,
            time_in_force=TimeInForce.GTC,
        )

        self.call_order_id = call_order.client_order_id
        self.put_order_id = put_order.client_order_id

        self.log.info(f"Submitting SELL Call order: {self.call_order_id.value} (Qty: {qty})")
        self.submit_order(call_order)

        self.log.info(f"Submitting SELL Put order: {self.put_order_id.value} (Qty: {qty})")
        self.submit_order(put_order)

    def on_order_submitted(self, event: OrderSubmitted) -> None:
        self.log.info(f"[ORDER SUBMITTED] ID: {event.client_order_id.value} | Inst: {event.instrument_id.value}")

    def on_order_accepted(self, event: OrderAccepted) -> None:
        self.log.info(f"[ORDER ACCEPTED] ID: {event.client_order_id.value} | Venue Order ID: {event.venue_order_id.value}")

    def on_order_rejected(self, event: OrderRejected) -> None:
        self.log.error(f"[ORDER REJECTED] ID: {event.client_order_id.value} | Reason: {event.reason}")
        self._handle_leg_failure(event.client_order_id)

    def on_order_canceled(self, event: OrderCanceled) -> None:
        self.log.warning(f"[ORDER CANCELED] ID: {event.client_order_id.value}")

    def on_order_filled(self, event: OrderFilled) -> None:
        """
        Track order executions and record entry premiums.
        """
        filled_px = float(event.last_px)
        filled_qty = Decimal(str(event.last_qty))

        self.log.info(
            f"[ORDER FILLED] ID: {event.client_order_id.value} | "
            f"Side: {event.order_side} | Qty: {filled_qty} | Price: {filled_px:.4f}"
        )

        if event.client_order_id == self.call_order_id:
            self.call_filled_qty += filled_qty
            self.call_entry_price = filled_px
        elif event.client_order_id == self.put_order_id:
            self.put_filled_qty += filled_qty
            self.put_entry_price = filled_px

        # Check if both legs have completed entry
        target_qty = self.config.contract_qty
        if self.call_filled_qty >= target_qty and self.put_filled_qty >= target_qty:
            if not self.straddle_entered:
                self.straddle_entered = True
                self.combined_entry_premium = self.call_entry_price + self.put_entry_price

                self.log.info("=" * 60)
                self.log.info("SHORT STRADDLE POSITION FULLY ESTABLISHED")
                self.log.info(f"  Call Entry Price: {self.call_entry_price:.4f}")
                self.log.info(f"  Put Entry Price:  {self.put_entry_price:.4f}")
                self.log.info(f"  Combined Entry Premium: {self.combined_entry_premium:.4f}")

                if self.config.use_risk_management:
                    # SL: 1% increase in buyback cost (paying more to buy back = loss)
                    self.stop_loss_trigger_price = calculate_stop_loss_price(
                        self.combined_entry_premium, self.config.stop_loss_pct
                    )
                    # TP: 2% decrease in buyback cost (paying less to buy back = profit)
                    self.take_profit_trigger_price = calculate_take_profit_price(
                        self.combined_entry_premium, self.config.take_profit_pct
                    )

                    self.log.info(f"  Level 2 Risk Management Active:")
                    self.log.info(f"  -> Stop-Loss Threshold (+{self.config.stop_loss_pct*100:.1f}%): >= {self.stop_loss_trigger_price:.4f}")
                    self.log.info(f"  -> Take-Profit Threshold (-{self.config.take_profit_pct*100:.1f}%): <= {self.take_profit_trigger_price:.4f}")
                else:
                    self.log.info("  Level 1 Mode: No automated Stop-Loss / Take-Profit configured.")
                self.log.info("=" * 60)

    def on_position_opened(self, position: Position) -> None:
        self.log.info(
            f"[POSITION OPENED] ID: {position.id.value} | Inst: {position.instrument_id.value} | "
            f"Side: {position.side} | Qty: {position.quantity} | Avg Open: {position.avg_px_open}"
        )

    def on_position_changed(self, position: Position) -> None:
        self.log.info(
            f"[POSITION CHANGED] ID: {position.id.value} | Inst: {position.instrument_id.value} | "
            f"Side: {position.side} | Qty: {position.quantity} | Realized PnL: {position.realized_pnl}"
        )

    def on_position_closed(self, position: Position) -> None:
        self.log.info(
            f"[POSITION CLOSED] ID: {position.id.value} | Inst: {position.instrument_id.value} | "
            f"Realized PnL: {position.realized_pnl}"
        )
        self._check_all_positions_closed()

    def _evaluate_risk_management(self) -> None:
        """
        Continuously evaluate Stop-Loss and Take-Profit conditions (Level 2).
        Calculates combined buyback premium using ask quotes for both legs.
        """
        if not self.config.use_risk_management:
            return

        if not self.straddle_entered or self.is_exiting or self.is_closed:
            return

        if self.latest_call_ask is None or self.latest_put_ask is None:
            return

        # Buyback valuation uses ask-side quotes per challenge specifications
        current_buyback_premium = self.latest_call_ask + self.latest_put_ask
        pct_change = ((current_buyback_premium - self.combined_entry_premium) / self.combined_entry_premium) * 100

        signal = evaluate_exit_signal(
            current_buyback_premium=current_buyback_premium,
            stop_loss_trigger=self.stop_loss_trigger_price,
            take_profit_trigger=self.take_profit_trigger_price,
        )

        if signal == "STOP-LOSS":
            self.log.warning(
                f"[RISK MANAGEMENT] STOP-LOSS TRIGGERED! "
                f"Combined buyback {current_buyback_premium:.4f} >= SL threshold {self.stop_loss_trigger_price:.4f} "
                f"({pct_change:+.2f}% vs +{self.config.stop_loss_pct*100:.1f}%)"
            )
            self._close_straddle_positions(reason="STOP-LOSS")
        elif signal == "TAKE-PROFIT":
            self.log.info(
                f"[RISK MANAGEMENT] TAKE-PROFIT TRIGGERED! "
                f"Combined buyback {current_buyback_premium:.4f} <= TP threshold {self.take_profit_trigger_price:.4f} "
                f"({pct_change:+.2f}% vs -{self.config.take_profit_pct*100:.1f}%)"
            )
            self._close_straddle_positions(reason="TAKE-PROFIT")

    def _close_straddle_positions(self, reason: str) -> None:
        """
        Atomically close both legs with duplicate-exit protection and proper sizing.
        """
        # Guard against duplicate exit attempts
        if self.is_exiting:
            self.log.warning("Exit already in progress. Ignoring duplicate trigger.")
            return

        self.is_exiting = True
        self.log.info(f"Initiating Straddle Closure: Reason={reason}")

        # Close open positions for both instruments
        for inst in (self.call_instrument, self.put_instrument):
            if inst is None:
                continue
            position = self.portfolio.position(inst.id) if self.portfolio is not None else None
            if position is not None and position.is_open:
                self.log.info(
                    f"Submitting closing BUY order for {inst.id.value} (Qty: {position.quantity}, Reduce-Only: True)"
                )
                self.close_position(position, reduce_only=True)
            else:
                self.log.info(f"No open position found to close for {inst.id.value}")

    def _handle_leg_failure(self, failed_order_id: ClientOrderId) -> None:
        """
        Handle execution failure or rejection of one leg (Question 10).
        Prevents carrying unhedged naked directional risk.
        """
        self.log.warning(f"Leg failure detected for order: {failed_order_id.value}")

        if failed_order_id == self.call_order_id:
            # Call failed. Cancel put order if open, or flatten put if filled
            self._flatten_single_leg(self.put_instrument, self.put_order_id, "Call leg rejected/failed")
        elif failed_order_id == self.put_order_id:
            # Put failed. Cancel call order if open, or flatten call if filled
            self._flatten_single_leg(self.call_instrument, self.call_order_id, "Put leg rejected/failed")

    def _flatten_single_leg(
        self,
        partner_instrument: Optional[Instrument],
        partner_order_id: Optional[ClientOrderId],
        reason: str,
    ) -> None:
        """
        Cancel unfilled partner order or close filled partner position.
        """
        if partner_instrument is None:
            return

        # 1. Cancel pending partner order if still working
        if partner_order_id is not None and self.cache is not None:
            order = self.cache.order(partner_order_id)
            if order and order.status in (OrderStatus.SUBMITTED, OrderStatus.ACCEPTED):
                self.log.warning(f"Canceling unfilled partner order {partner_order_id.value} due to: {reason}")
                self.cancel_order(order)

        # 2. Close partner position if already opened
        position = self.portfolio.position(partner_instrument.id) if self.portfolio is not None else None
        if position is not None and position.is_open:
            self.log.warning(
                f"Closing unhedged leg {partner_instrument.id.value} (Qty: {position.quantity}) to protect against directional risk!"
            )
            self.close_position(position, reduce_only=True)

    def _check_all_positions_closed(self) -> None:
        """
        Verify when all straddle positions are fully closed.
        """
        call_pos = self.portfolio.position(self.call_instrument.id) if (self.call_instrument and self.portfolio is not None) else None
        put_pos = self.portfolio.position(self.put_instrument.id) if (self.put_instrument and self.portfolio is not None) else None

        call_closed = call_pos is None or call_pos.is_closed
        put_closed = put_pos is None or put_pos.is_closed

        if call_closed and put_closed and self.is_exiting:
            self.is_closed = True
            self.log.info("ALL STRADDLE POSITIONS SUCCESSFULLY CLOSED. STRATEGY COMPLETE.")

    def on_stop(self) -> None:
        """
        Called when the strategy is stopped.
        """
        self.log.info("BTCShortStraddleStrategy stopped.")

