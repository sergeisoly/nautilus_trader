from decimal import Decimal

import pytest
import asyncio

from nautilus_trader.adapters.aster.config import AsterInstrumentProviderConfig
from nautilus_trader.adapters.aster.providers import AsterInstrumentProvider
from nautilus_trader.common.component import LiveClock
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def test_load_all_handles_aster_time_in_force_rpi(monkeypatch, event_loop):
    clock = LiveClock()
    # Dummy HTTP client with base_url needed for provider init; not used in patched fetch.
    class DummyClient:
        base_url = "https://fapi.asterdex.com"

        # Stub methods used by BinanceHttpEndpoint during init (won't be called thanks to monkeypatch)
        async def send_request(self, *args, **kwargs):
            return b"{}"

        async def sign_request(self, *args, **kwargs):
            return b"{}"

    provider = AsterInstrumentProvider(
        client=DummyClient(),
        clock=clock,
        config=AsterInstrumentProviderConfig(load_all=True),
    )

    fixture = {
        "serverTime": 1700000000000,
        "symbols": [
            {
                "symbol": "FOOUSDT",
                "status": "TRADING",
                "baseAsset": "FOO",
                "quoteAsset": "USDT",
                "pricePrecision": 4,
                "quantityPrecision": 3,
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.0001"},
                    {"filterType": "LOT_SIZE", "stepSize": "0.001"},
                ],
                # ASTER adds RPI to timeInForce (not present in Binance enum)
                "timeInForce": ["GTC", "IOC", "FOK", "GTX", "RPI"],
            },
        ],
    }

    async def fake_fetch():
        return fixture

    monkeypatch.setattr(provider, "_fetch_exchange_info", fake_fetch)

    event_loop.run_until_complete(provider.load_all_async())

    instruments = provider.get_all()
    iid = InstrumentId(Symbol("FOOUSDT-PERP"), Venue("ASTERDEX"))
    assert iid in instruments
    inst = instruments[iid]
    from nautilus_trader.model.objects import Price, Quantity

    assert inst.price_increment == Price.from_str("0.0001")
    assert inst.size_increment == Quantity.from_str("0.001")
    assert inst.maker_fee == Decimal("0.00005")  # 0.5 bps default
    assert inst.taker_fee == Decimal("0.0004")   # 4 bps default


def test_load_ids_single_symbol(monkeypatch, event_loop):
    clock = LiveClock()

    class DummyClient:
        base_url = "https://fapi.asterdex.com"

        async def send_request(self, *args, **kwargs):
            return b"{}"

        async def sign_request(self, *args, **kwargs):
            return b"{}"

    provider = AsterInstrumentProvider(
        client=DummyClient(),
        clock=clock,
        config=AsterInstrumentProviderConfig(load_all=False),
    )

    fixture = {
        "serverTime": 1700000000000,
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "status": "TRADING",
                "baseAsset": "BTC",
                "quoteAsset": "USDT",
                "pricePrecision": 1,
                "quantityPrecision": 3,
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.1"},
                    {"filterType": "LOT_SIZE", "stepSize": "0.001"},
                ],
            },
        ],
    }

    async def fake_fetch():
        return fixture

    monkeypatch.setattr(provider, "_fetch_exchange_info", fake_fetch)

    event_loop.run_until_complete(
        provider.load_ids_async([InstrumentId(Symbol("BTCUSDT-PERP"), Venue("ASTERDEX"))])
    )

    instruments = provider.get_all()
    iid = InstrumentId(Symbol("BTCUSDT-PERP"), Venue("ASTERDEX"))
    assert iid in instruments
    inst = instruments[iid]
    from nautilus_trader.model.objects import Price, Quantity

    assert inst.price_increment == Price.from_str("0.1")
    assert inst.size_increment == Quantity.from_str("0.001")
