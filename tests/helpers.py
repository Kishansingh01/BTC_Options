from __future__ import annotations

from decimal import Decimal
from nautilus_trader.model.currencies import BTC, USDT
from nautilus_trader.model.enums import OptionKind
from nautilus_trader.model.identifiers import InstrumentId, Symbol
from nautilus_trader.model.instruments import CryptoOption, CryptoPerpetual
from nautilus_trader.model.objects import Price, Quantity


def create_test_crypto_option(
    strike: float,
    kind: OptionKind,
    expiry_str: str = "28MAR25",
    venue: str = "BYBIT",
) -> CryptoOption:
    kind_char = "C" if kind == OptionKind.CALL else "P"
    strike_int = int(strike)
    symbol_str = f"BTC-{expiry_str}-{strike_int}-{kind_char}-USDT"
    instrument_id_str = f"{symbol_str}-OPTION.{venue}"

    return CryptoOption(
        instrument_id=InstrumentId.from_str(instrument_id_str),
        raw_symbol=Symbol(symbol_str),
        underlying=BTC,
        quote_currency=USDT,
        settlement_currency=USDT,
        is_inverse=False,
        option_kind=kind,
        strike_price=Price.from_str(str(strike_int)),
        activation_ns=0,
        expiration_ns=1743148800000000000,
        price_precision=2,
        size_precision=2,
        price_increment=Price.from_str("0.50"),
        size_increment=Quantity.from_str("0.01"),
        ts_event=0,
        ts_init=0,
    )


def create_test_underlying_perp(
    symbol_str: str = "BTCUSDT-LINEAR",
    venue: str = "BYBIT",
) -> CryptoPerpetual:
    instrument_id_str = f"{symbol_str}.{venue}"
    return CryptoPerpetual(
        instrument_id=InstrumentId.from_str(instrument_id_str),
        raw_symbol=Symbol("BTCUSDT"),
        base_currency=BTC,
        quote_currency=USDT,
        settlement_currency=USDT,
        is_inverse=False,
        price_precision=2,
        size_precision=3,
        price_increment=Price.from_str("0.10"),
        size_increment=Quantity.from_str("0.001"),
        multiplier=Quantity.from_str("1"),
        lot_size=Quantity.from_str("0.001"),
        max_quantity=Quantity.from_str("100"),
        min_quantity=Quantity.from_str("0.001"),
        max_price=Price.from_str("1000000.00"),
        min_price=Price.from_str("1.00"),
        margin_init=Decimal("0.01"),
        margin_maint=Decimal("0.005"),
        maker_fee=Decimal("0.0002"),
        taker_fee=Decimal("0.0005"),
        ts_event=0,
        ts_init=0,
    )


from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.enums import LiquiditySide, OrderType
from nautilus_trader.model.events import OrderFilled
from nautilus_trader.model.identifiers import AccountId, PositionId, TradeId, TraderId, VenueOrderId
from nautilus_trader.model.objects import Money


def create_test_order_filled(
    strategy_id,
    instrument_id,
    client_order_id,
    order_side,
    last_qty,
    last_px,
    currency=USDT,
):
    return OrderFilled(
        trader_id=TraderId("TRADER-001"),
        strategy_id=strategy_id,
        instrument_id=instrument_id,
        client_order_id=client_order_id,
        venue_order_id=VenueOrderId("VENUE-001"),
        account_id=AccountId("BYBIT-001"),
        trade_id=TradeId("TRADE-001"),
        position_id=None,
        order_side=order_side,
        order_type=OrderType.MARKET,
        last_qty=Quantity.from_str(str(last_qty)),
        last_px=Price.from_str(str(last_px)),
        currency=currency,
        commission=Money(0, currency),
        liquidity_side=LiquiditySide.TAKER,
        event_id=UUID4(),
        ts_event=1000,
        ts_init=1000,
    )
