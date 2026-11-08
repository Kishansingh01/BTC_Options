from __future__ import annotations

import pytest
from decimal import Decimal
from unittest.mock import MagicMock

from nautilus_trader.model.enums import OptionKind, OrderSide, OrderStatus
from nautilus_trader.model.events import OrderFilled, OrderRejected
from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId, TraderId
from nautilus_trader.model.objects import Price, Quantity

from strategy.straddle import (
    BTCShortStraddleConfig,
    BTCShortStraddleStrategy,
    calculate_stop_loss_price,
    calculate_take_profit_price,
    evaluate_exit_signal,
)
from tests.helpers import create_test_crypto_option, create_test_order_filled


def test_calculate_stop_loss_threshold():
    entry_premium = 3000.0
    # Stop-Loss is +1% increase in buyback premium
    sl_price = calculate_stop_loss_price(entry_premium, stop_loss_pct=0.01)
    assert sl_price == pytest.approx(3030.0)


def test_calculate_take_profit_threshold():
    entry_premium = 3000.0
    # Take-Profit is -2% decrease in buyback premium
    tp_price = calculate_take_profit_price(entry_premium, take_profit_pct=0.02)
    assert tp_price == pytest.approx(2940.0)


def test_evaluate_exit_signal_triggers():
    sl_threshold = 3030.0
    tp_threshold = 2940.0

    # 1. Neutral price between TP and SL -> None
    assert evaluate_exit_signal(3000.0, sl_threshold, tp_threshold) is None
    assert evaluate_exit_signal(3029.9, sl_threshold, tp_threshold) is None
    assert evaluate_exit_signal(2940.1, sl_threshold, tp_threshold) is None

    # 2. Stop-Loss Trigger (>= 3030.0)
    assert evaluate_exit_signal(3030.0, sl_threshold, tp_threshold) == "STOP-LOSS"
    assert evaluate_exit_signal(3050.0, sl_threshold, tp_threshold) == "STOP-LOSS"

    # 3. Take-Profit Trigger (<= 2940.0)
    assert evaluate_exit_signal(2940.0, sl_threshold, tp_threshold) == "TAKE-PROFIT"
    assert evaluate_exit_signal(2900.0, sl_threshold, tp_threshold) == "TAKE-PROFIT"


def test_strategy_order_fill_and_risk_threshold_init():
    cfg = BTCShortStraddleConfig(
        underlying_instrument_id="BTCUSDT-LINEAR.BYBIT",
        contract_qty=Decimal("0.01"),
        use_risk_management=True,
        stop_loss_pct=0.01,
        take_profit_pct=0.02,
    )
    strategy = BTCShortStraddleStrategy(cfg)
    strategy.submit_order = MagicMock()
    strategy.close_position = MagicMock()

    call_opt = create_test_crypto_option(85000, OptionKind.CALL)
    put_opt = create_test_crypto_option(85000, OptionKind.PUT)
    strategy.call_instrument = call_opt
    strategy.put_instrument = put_opt
    strategy.call_order_id = ClientOrderId("CALL-001")
    strategy.put_order_id = ClientOrderId("PUT-001")

    # Simulate Call fill at 1600.00
    fill_call = create_test_order_filled(
        strategy_id=strategy.id,
        instrument_id=call_opt.id,
        client_order_id=strategy.call_order_id,
        order_side=OrderSide.SELL,
        last_qty="0.01",
        last_px="1600.00",
    )
    strategy.on_order_filled(fill_call)
    assert strategy.straddle_entered is False  # Put not filled yet

    # Simulate Put fill at 1400.00
    fill_put = create_test_order_filled(
        strategy_id=strategy.id,
        instrument_id=put_opt.id,
        client_order_id=strategy.put_order_id,
        order_side=OrderSide.SELL,
        last_qty="0.01",
        last_px="1400.00",
    )
    strategy.on_order_filled(fill_put)

    assert strategy.straddle_entered is True
    assert strategy.combined_entry_premium == 3000.0
    assert strategy.stop_loss_trigger_price == pytest.approx(3030.0)
    assert strategy.take_profit_trigger_price == pytest.approx(2940.0)


def test_duplicate_exit_prevention_flag():
    cfg = BTCShortStraddleConfig(
        underlying_instrument_id="BTCUSDT-LINEAR.BYBIT",
        contract_qty=Decimal("0.01"),
        use_risk_management=True,
    )
    strategy = BTCShortStraddleStrategy(cfg)
    strategy.close_position = MagicMock()
    strategy.straddle_entered = True
    strategy.combined_entry_premium = 3000.0
    strategy.stop_loss_trigger_price = 3030.0
    strategy.take_profit_trigger_price = 2940.0
    strategy.is_exiting = True  # Already marked as exiting

    # Provide ask quotes that exceed Stop-Loss
    strategy.latest_call_ask = 1600.0
    strategy.latest_put_ask = 1600.0
    strategy._evaluate_risk_management()

    # close_position should not be called again
    strategy.close_position.assert_not_called()


def test_level1_mode_ignores_sl_tp():
    cfg = BTCShortStraddleConfig(
        underlying_instrument_id="BTCUSDT-LINEAR.BYBIT",
        contract_qty=Decimal("0.01"),
        use_risk_management=False,  # Level 1 Naked Straddle
    )
    strategy = BTCShortStraddleStrategy(cfg)
    strategy.close_position = MagicMock()
    strategy.straddle_entered = True
    strategy.combined_entry_premium = 3000.0

    # Large move that would otherwise trigger SL
    strategy.latest_call_ask = 2500.0
    strategy.latest_put_ask = 2500.0
    strategy._evaluate_risk_management()

    strategy.close_position.assert_not_called()
    assert strategy.is_exiting is False
