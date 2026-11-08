from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from unittest.mock import MagicMock

from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.enums import OptionKind, OrderSide
from nautilus_trader.model.identifiers import ClientOrderId
from nautilus_trader.model.objects import Price, Quantity

from strategy.selector import find_atm_straddle_pair
from strategy.straddle import (
    BTCShortStraddleConfig,
    BTCShortStraddleStrategy,
    calculate_stop_loss_price,
    calculate_take_profit_price,
    evaluate_exit_signal,
)
from tests.helpers import (
    create_test_crypto_option,
    create_test_order_filled,
    create_test_underlying_perp,
)


def run_simulation(scenario: str = "sl", level: int = 2):
    print("=" * 75)
    print(f"NAUTILUSTRADER BTC SHORT STRADDLE SIMULATION (Scenario: {scenario.upper()}, Level: {level})")
    print("=" * 75)

    # 1. Setup available option instruments at strikes around 85,000
    strikes = [80000, 82000, 84000, 85000, 86000, 88000, 90000]
    instruments = []
    for s in strikes:
        instruments.append(create_test_crypto_option(s, OptionKind.CALL, expiry_str="28MAR25"))
        instruments.append(create_test_crypto_option(s, OptionKind.PUT, expiry_str="28MAR25"))

    underlying = create_test_underlying_perp()
    instruments.append(underlying)

    # 2. Reference price arrives
    btc_spot_price = 85150.0
    print(f"\n[STEP 1] BTC Underlying Price Received: ${btc_spot_price:,.2f}")

    pair = find_atm_straddle_pair(instruments, reference_price=btc_spot_price)
    assert pair is not None
    call_inst, put_inst, selected_strike, expiry = pair

    print(f"         ATM Strike Selected: ${selected_strike:,.0f} (Nearest to ${btc_spot_price:,.2f})")
    print(f"         Option Expiry: {expiry}")
    print(f"         Call Leg: {call_inst.id.value}")
    print(f"         Put Leg:  {put_inst.id.value}")

    # 3. Strategy Configuration & Order Submission
    use_rm = (level == 2)
    cfg = BTCShortStraddleConfig(
        underlying_instrument_id=underlying.id.value,
        contract_qty=Decimal("0.01"),
        use_risk_management=use_rm,
        stop_loss_pct=0.01,
        take_profit_pct=0.02,
    )
    strategy = BTCShortStraddleStrategy(cfg)
    strategy.submit_order = MagicMock()
    strategy.close_position = MagicMock()
    strategy.call_instrument = call_inst
    strategy.put_instrument = put_inst

    # Mock order IDs
    call_order_id = ClientOrderId("SELL-CALL-001")
    put_order_id = ClientOrderId("SELL-PUT-001")
    strategy.call_order_id = call_order_id
    strategy.put_order_id = put_order_id

    print(f"\n[STEP 2] Submitting Sell Orders for 0.01 BTC ATM Straddle:")
    print(f"         -> SELL 0.01 {call_inst.id.value}")
    print(f"         -> SELL 0.01 {put_inst.id.value}")

    # 4. Simulating Fills
    call_entry_px = 1800.00
    put_entry_px = 1600.00
    fill_call = create_test_order_filled(
        strategy_id=strategy.id,
        instrument_id=call_inst.id,
        client_order_id=call_order_id,
        order_side=OrderSide.SELL,
        last_qty="0.01",
        last_px=str(call_entry_px),
    )
    fill_put = create_test_order_filled(
        strategy_id=strategy.id,
        instrument_id=put_inst.id,
        client_order_id=put_order_id,
        order_side=OrderSide.SELL,
        last_qty="0.01",
        last_px=str(put_entry_px),
    )

    strategy.on_order_filled(fill_call)
    strategy.on_order_filled(fill_put)

    combined_entry = call_entry_px + put_entry_px
    print(f"\n[STEP 3] Fills Confirmed & Positions Opened:")
    print(f"         Call Fill Price: ${call_entry_px:,.2f}")
    print(f"         Put Fill Price:  ${put_entry_px:,.2f}")
    print(f"         Combined Entry Premium: ${combined_entry:,.2f}")

    if use_rm:
        sl_threshold = calculate_stop_loss_price(combined_entry, cfg.stop_loss_pct)
        tp_threshold = calculate_take_profit_price(combined_entry, cfg.take_profit_pct)
        print(f"         [Risk Management] Stop-Loss   (+1.0% buyback cost): >= ${sl_threshold:,.2f}")
        print(f"         [Risk Management] Take-Profit (-2.0% buyback cost): <= ${tp_threshold:,.2f}")
    else:
        print("         [Level 1] Automated Risk Management disabled (no SL/TP).")

    # 5. Stream Market Quote Updates
    print(f"\n[STEP 4] Streaming Live Market Quotes for Both Option Legs...")
    if scenario == "sl":
        # Simulate price volatility expanding option premiums
        ticks = [
            (1805.0, 1605.0),  # Buyback = 3410 (+0.29%)
            (1815.0, 1615.0),  # Buyback = 3430 (+0.88%)
            (1822.0, 1620.0),  # Buyback = 3442 (+1.24% >= SL threshold 3434.00)
        ]
    elif scenario == "tp":
        # Simulate time decay (theta) eroding option premiums
        ticks = [
            (1790.0, 1590.0),  # Buyback = 3380 (-0.59%)
            (1775.0, 1575.0),  # Buyback = 3350 (-1.47%)
            (1760.0, 1565.0),  # Buyback = 3325 (-2.21% <= TP threshold 3332.00)
        ]
    else:  # neutral / level 1
        ticks = [
            (1850.0, 1650.0),
            (1900.0, 1700.0),
        ]

    for i, (call_ask, put_ask) in enumerate(ticks, 1):
        strategy.latest_call_ask = call_ask
        strategy.latest_put_ask = put_ask
        buyback = call_ask + put_ask
        pct_change = ((buyback - combined_entry) / combined_entry) * 100

        print(f"         Tick {i}: Call Ask=${call_ask:,.2f} | Put Ask=${put_ask:,.2f} -> Buyback=${buyback:,.2f} ({pct_change:+.2f}%)")
        strategy._evaluate_risk_management()

        if strategy.is_exiting:
            print(f"\n[STEP 5] EXIT TRIGGER ACTIVATED!")
            print(f"         Strategy initiated closing orders for both legs (Reduce-Only: True).")
            print(f"         Duplicate exit protection: is_exiting = {strategy.is_exiting}")
            break

    if not strategy.is_exiting:
        print(f"\n[STEP 5] Positions remain OPEN (no automated exit).")

    print("\n" + "=" * 75)
    print("SIMULATION EXECUTION SUCCESSFUL")
    print("=" * 75 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BTC Options Straddle Simulator")
    parser.add_argument("--scenario", choices=["sl", "tp", "neutral"], default="sl", help="Simulation scenario")
    parser.add_argument("--level", type=int, choices=[1, 2], default=2, help="Level 1 (naked) or Level 2 (with RM)")
    args = parser.parse_args()
    run_simulation(scenario=args.scenario, level=args.level)

