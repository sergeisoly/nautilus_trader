# -------------------------------------------------------------------------------------------------
#  Copyright (C) 2015-2025 Nautech Systems Pty Ltd. All rights reserved.
#  https://nautechsystems.io
#
#  Licensed under the GNU Lesser General Public License Version 3.0 (the "License");
#  You may not use this file except in compliance with the License.
#  You may obtain a copy of the License at https://www.gnu.org/licenses/lgpl-3.0.en.html
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
# -------------------------------------------------------------------------------------------------

from __future__ import annotations

import json
from decimal import Decimal

from nautilus_trader.adapters.aster.config import AsterInstrumentProviderConfig
from nautilus_trader.adapters.aster.constants import ASTER_VENUE
from nautilus_trader.adapters.binance.common.enums import BinanceAccountType
from nautilus_trader.adapters.binance.common.symbol import BinanceSymbol
from nautilus_trader.adapters.binance.futures.providers import BinanceFuturesInstrumentProvider
from nautilus_trader.adapters.binance.http.client import BinanceHttpClient
from nautilus_trader.common.component import LiveClock
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.core.nautilus_pyo3 import HttpMethod
from nautilus_trader.model.identifiers import Venue
from nautilus_trader.model.identifiers import InstrumentId, Symbol
from nautilus_trader.model.instruments.crypto_perpetual import CryptoPerpetual
from nautilus_trader.model.objects import Currency, Price, Quantity


class AsterInstrumentProvider(BinanceFuturesInstrumentProvider):
    """
    Thin wrapper over Binance futures instrument provider, pointing to ASTER endpoints/venue.
    """

    def __init__(
        self,
        client: BinanceHttpClient,
        clock: LiveClock,
        config: InstrumentProviderConfig | AsterInstrumentProviderConfig | None = None,
        venue: Venue = ASTER_VENUE,
    ) -> None:
        super().__init__(
            client=client,
            clock=clock,
            account_type=BinanceAccountType.USDT_FUTURES,
            config=config,
            venue=venue,
        )

    # Override to handle ASTER-specific exchangeInfo (extra TIF 'RPI')
    async def load_all_async(self, filters: dict | None = None) -> None:
        filters = filters or self._filters
        data = await self._fetch_exchange_info()
        server_time = data.get("serverTime", 0)
        instruments = 0
        for symbol_info in data.get("symbols", []):
            if self._parse_instrument_dict(symbol_info, server_time, filters):
                instruments += 1
        if instruments == 0:
            self._log.warning("No ASTER instruments loaded (check filters?)")

    async def load_ids_async(self, instrument_ids: list[InstrumentId], filters: dict | None = None) -> None:
        if not instrument_ids:
            self._log.warning("No instrument IDs given for loading.")
            return
        for instrument_id in instrument_ids:
            if instrument_id.venue != self._venue:
                self._log.warning("Skipping instrument %s: wrong venue", instrument_id)
                return
        data = await self._fetch_exchange_info()
        server_time = data.get("serverTime", 0)
        sym_map = {s.get("symbol"): s for s in data.get("symbols", [])}
        for instrument_id in instrument_ids:
            # Instrument IDs in Nautilus follow Binance futures convention: "<RAW>-PERP".
            # ASTER exchangeInfo lists raw symbols without "-PERP", so normalize first.
            sym = str(BinanceSymbol(instrument_id.symbol.value))
            info = sym_map.get(sym)
            if not info:
                self._log.warning("Symbol %s not found in exchangeInfo", sym)
                continue
            self._parse_instrument_dict(info, server_time, filters or {})

    # ------------------------------------------------------------------ helpers
    async def _fetch_exchange_info(self) -> dict:
        # Use Nautilus HTTP client (pyo3) rather than urllib.
        # This keeps behavior consistent with the live data/execution clients and avoids
        # environment-specific TLS verification issues (e.g. VPN MITM cert chains).
        raw = await self._client.send_request(HttpMethod.GET, "/fapi/v1/exchangeInfo")
        return json.loads(raw.decode())

    def _parse_instrument_dict(self, info: dict, server_time_ms: int, filters: dict | None) -> bool:
        # Basic status checks
        if info.get("status") != "TRADING":
            return False

        symbol_str = info.get("symbol")
        if not symbol_str:
            return False

        # Apply filters if any (reuse parent logic signature)
        if filters:
            # simple symbol allow list
            allow = filters.get("symbols")
            if allow and symbol_str not in allow:
                return False

        # Filters extraction
        price_filter = next((f for f in info.get("filters", []) if f.get("filterType") == "PRICE_FILTER"), None)
        lot_filter = next((f for f in info.get("filters", []) if f.get("filterType") == "LOT_SIZE"), None)
        if not price_filter or not lot_filter:
            self._log.warning("Missing PRICE_FILTER or LOT_SIZE for %s", symbol_str)
            return False

        tick_size = price_filter.get("tickSize", "0.0")
        step_size = lot_filter.get("stepSize", "0.0")

        price_increment = Price.from_str(tick_size)
        size_increment = Quantity.from_str(step_size)
        price_precision = price_increment.precision
        size_precision = size_increment.precision

        maker_fee = Decimal(str(getattr(self._config, "maker_bps", 0.5))) / Decimal(10_000)
        taker_fee = Decimal(str(getattr(self._config, "taker_bps", 4.0))) / Decimal(10_000)

        raw_symbol = Symbol(symbol_str)
        # Keep instrument_id aligned with Binance futures symbol normalization ("-PERP").
        nautilus_symbol = Symbol(BinanceSymbol(raw_symbol.value).parse_as_nautilus(BinanceAccountType.USDT_FUTURES))

        instrument = CryptoPerpetual(
            instrument_id=InstrumentId(nautilus_symbol, self._venue),
            raw_symbol=raw_symbol,
            base_currency=Currency.from_str(info.get("baseAsset", "BTC")),
            quote_currency=Currency.from_str(info.get("quoteAsset", "USDT")),
            settlement_currency=Currency.from_str(info.get("quoteAsset", "USDT")),
            is_inverse=False,
            price_precision=price_precision,
            size_precision=size_precision,
            price_increment=price_increment,
            size_increment=size_increment,
            ts_event=server_time_ms * 1_000_000,
            ts_init=server_time_ms * 1_000_000,
            maker_fee=maker_fee,
            taker_fee=taker_fee,
        )

        # Register currencies and store
        self.add_currency(currency=instrument.base_currency)
        self.add_currency(currency=instrument.quote_currency)
        self.add(instrument=instrument)
        return True
