from __future__ import annotations

import logging
from typing import Sequence
from nautilus_trader.model.enums import OptionKind
from nautilus_trader.model.instruments import CryptoOption, Instrument

logger = logging.getLogger(__name__)


def is_btc_option(instrument: Instrument) -> bool:
    """
    Check if an instrument is a BTC option.
    """
    if isinstance(instrument, CryptoOption):
        underlying = getattr(instrument, "underlying", None)
        underlying_str = str(underlying) if underlying else ""
        return "BTC" in underlying_str or "BTC" in instrument.id.value
    raw = instrument.id.value
    return "BTC" in raw and ("-C" in raw or "-P" in raw)


def find_atm_straddle_pair(
    instruments: Sequence[Instrument],
    reference_price: float,
    target_expiry: str | None = None,
) -> tuple[Instrument, Instrument, float, any] | None:
    """
    Find the nearest At-The-Money (ATM) Call and Put options pair with the exact same
    strike and expiry for a given underlying reference price.

    Parameters
    ----------
    instruments : Sequence[Instrument]
        List of instruments loaded in the cache / provider.
    reference_price : float
        Current BTC underlying reference price (e.g. from spot/perpetual ticker).
    target_expiry : str | None, optional
        Optional target expiry string to filter by (e.g. "27DEC24" or date string).
        If None, the nearest active expiry date with valid Call & Put pairs is selected.

    Returns
    -------
    tuple[Instrument, Instrument, float, any] | None
        (call_instrument, put_instrument, strike_price, expiry)
        or None if no suitable pair was found.
    """
    btc_options = [inst for inst in instruments if is_btc_option(inst)]
    if not btc_options:
        logger.warning("No BTC options found in instruments collection")
        return None

    # Group by expiry
    by_expiry: dict[any, list[Instrument]] = {}
    for inst in btc_options:
        expiry = getattr(inst, "expiration_utc", None)
        if expiry is None:
            # Fallback to parsing expiry from symbol (e.g., BTC-27DEC24-...)
            parts = inst.raw_symbol.value.split("-") if hasattr(inst.raw_symbol, "value") else str(inst.raw_symbol).split("-")
            if len(parts) >= 2:
                expiry = parts[1]
            else:
                expiry = "UNKNOWN"
        by_expiry.setdefault(expiry, []).append(inst)

    # Sort expiries: prefer target_expiry if provided, else upcoming
    expiries = list(by_expiry.keys())
    if target_expiry:
        expiries = [e for e in expiries if target_expiry in str(e)]
        if not expiries:
            logger.warning("No option expiries matched target_expiry: %s", target_expiry)
            return None
    else:
        # Sort expiries ascending
        try:
            expiries.sort(key=lambda x: str(x))
        except Exception:
            pass

    for expiry in expiries:
        exp_instruments = by_expiry[expiry]
        strikes_map: dict[float, dict[str, Instrument]] = {}

        for inst in exp_instruments:
            # Determine strike
            strike = None
            if hasattr(inst, "strike_price") and inst.strike_price is not None:
                strike = float(inst.strike_price)
            else:
                # Parse from symbol BTC-24SEP27-65000-P-USDT
                parts = str(inst.raw_symbol).split("-")
                if len(parts) >= 3:
                    try:
                        strike = float(parts[2])
                    except ValueError:
                        continue

            if strike is None:
                continue

            # Determine kind (Call or Put)
            kind = None
            if hasattr(inst, "option_kind"):
                if inst.option_kind == OptionKind.CALL:
                    kind = "CALL"
                elif inst.option_kind == OptionKind.PUT:
                    kind = "PUT"
            
            if kind is None:
                symbol_str = str(inst.raw_symbol)
                if "-C" in symbol_str:
                    kind = "CALL"
                elif "-P" in symbol_str:
                    kind = "PUT"

            if not kind:
                continue

            strikes_map.setdefault(strike, {})[kind] = inst

        # Keep only strikes that have both CALL and PUT
        valid_strikes = [
            s for s, pair in strikes_map.items()
            if "CALL" in pair and "PUT" in pair
        ]

        if not valid_strikes:
            continue

        # Find nearest strike to reference price
        nearest_strike = min(valid_strikes, key=lambda s: abs(s - reference_price))
        call_inst = strikes_map[nearest_strike]["CALL"]
        put_inst = strikes_map[nearest_strike]["PUT"]

        logger.info(
            f"Selected ATM straddle for expiry {expiry}: "
            f"Strike={nearest_strike} (Diff from ref {reference_price:.2f}: {abs(nearest_strike - reference_price):.2f}) | "
            f"Call={call_inst.id.value} | Put={put_inst.id.value}"
        )
        return call_inst, put_inst, nearest_strike, expiry

    logger.warning("Could not find any complete Call/Put pair for available expiries")
    return None
