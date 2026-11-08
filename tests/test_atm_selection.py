from __future__ import annotations

import pytest
from nautilus_trader.model.enums import OptionKind
from strategy.selector import find_atm_straddle_pair, is_btc_option
from tests.helpers import create_test_crypto_option


def test_atm_strike_selection_nearest():
    # Setup strikes at 80k, 84k, 85k, 90k
    strikes = [80000, 84000, 85000, 90000]
    instruments = []
    for s in strikes:
        instruments.append(create_test_crypto_option(s, OptionKind.CALL, expiry_str="28MAR25"))
        instruments.append(create_test_crypto_option(s, OptionKind.PUT, expiry_str="28MAR25"))

    # Test 1: Underlying at 84,200 -> Nearest strike is 84,000
    pair = find_atm_straddle_pair(instruments, reference_price=84200.0)
    assert pair is not None
    call_inst, put_inst, strike, expiry = pair
    assert strike == 84000
    assert call_inst.option_kind == OptionKind.CALL
    assert put_inst.option_kind == OptionKind.PUT
    assert call_inst.strike_price == 84000
    assert put_inst.strike_price == 84000

    # Test 2: Underlying at 84,800 -> Nearest strike is 85,000
    pair = find_atm_straddle_pair(instruments, reference_price=84800.0)
    assert pair is not None
    _, _, strike, _ = pair
    assert strike == 85000


def test_atm_selection_requires_both_call_and_put():
    # 84000 has only CALL, 85000 has both CALL and PUT
    instruments = [
        create_test_crypto_option(84000, OptionKind.CALL, expiry_str="28MAR25"),
        # Missing 84000 PUT
        create_test_crypto_option(85000, OptionKind.CALL, expiry_str="28MAR25"),
        create_test_crypto_option(85000, OptionKind.PUT, expiry_str="28MAR25"),
    ]

    # Even though 84,100 is closer to 84,000, 84,000 lacks a PUT leg, so 85,000 must be chosen
    pair = find_atm_straddle_pair(instruments, reference_price=84100.0)
    assert pair is not None
    _, _, strike, _ = pair
    assert strike == 85000


def test_is_btc_option():
    opt = create_test_crypto_option(85000, OptionKind.CALL)
    assert is_btc_option(opt) is True

