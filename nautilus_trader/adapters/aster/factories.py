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

import asyncio
from typing import Any

from nautilus_trader.adapters.aster.config import (
    AsterDataClientConfig,
    AsterExecClientConfig,
    AsterInstrumentProviderConfig,
)
from nautilus_trader.adapters.aster.constants import ASTER_BASE_URL_HTTP
from nautilus_trader.adapters.aster.data import AsterMarketDataClient
from nautilus_trader.adapters.aster.execution import AsterExecutionClient
from nautilus_trader.adapters.aster.providers import AsterInstrumentProvider
from nautilus_trader.adapters.binance.common.enums import BinanceAccountType, BinanceKeyType
from nautilus_trader.adapters.binance.http.client import BinanceHttpClient
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock
from nautilus_trader.common.component import MessageBus
from nautilus_trader.live.factories import LiveDataClientFactory, LiveExecClientFactory


def create_aster_http_client(
    clock: LiveClock,
    api_key: str | None = None,
    api_secret: str | None = None,
    base_url: str | None = None,
    proxy_url: str | None = None,
) -> BinanceHttpClient:
    return BinanceHttpClient(
        clock=clock,
        api_key=api_key or "",
        api_secret=api_secret or "",
        base_url=base_url or ASTER_BASE_URL_HTTP,
        key_type=BinanceKeyType.HMAC,
        proxy_url=proxy_url,
    )


def create_aster_instrument_provider(
    clock: LiveClock,
    api_key: str | None = None,
    api_secret: str | None = None,
    config: AsterInstrumentProviderConfig | None = None,
    proxy_url: str | None = None,
) -> AsterInstrumentProvider:
    client = create_aster_http_client(
        clock=clock,
        api_key=api_key,
        api_secret=api_secret,
        proxy_url=proxy_url,
    )
    return AsterInstrumentProvider(
        client=client,
        clock=clock,
        config=config,
    )


def create_aster_market_data_client(
    loop: asyncio.AbstractEventLoop,
    msgbus: MessageBus,
    cache: Cache,
    clock: LiveClock,
    instrument_provider: AsterInstrumentProvider,
    config: AsterDataClientConfig,
    api_key: str | None = None,
    api_secret: str | None = None,
    proxy_url: str | None = None,
    name: str | None = None,
) -> AsterMarketDataClient:
    client = create_aster_http_client(
        clock=clock,
        api_key=api_key,
        api_secret=api_secret,
        base_url=config.base_url_http,
        proxy_url=proxy_url,
    )
    return AsterMarketDataClient(
        loop=loop,
        client=client,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        instrument_provider=instrument_provider,
        config=config,
        name=name,
    )


def create_aster_execution_client(
    loop: asyncio.AbstractEventLoop,
    msgbus: MessageBus,
    cache: Cache,
    clock: LiveClock,
    instrument_provider: AsterInstrumentProvider,
    config: AsterExecClientConfig,
    api_key: str | None = None,
    api_secret: str | None = None,
    proxy_url: str | None = None,
    name: str | None = None,
) -> AsterExecutionClient:
    client = create_aster_http_client(
        clock=clock,
        api_key=api_key,
        api_secret=api_secret,
        base_url=config.base_url_http,
        proxy_url=proxy_url,
    )
    return AsterExecutionClient(
        loop=loop,
        client=client,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        instrument_provider=instrument_provider,
        config=config,
        name=name,
    )


_CACHED_PROVIDER: AsterInstrumentProvider | None = None


def _get_cached_provider(*, clock: LiveClock, proxy_url: str | None, config: AsterInstrumentProviderConfig | None) -> AsterInstrumentProvider:
    global _CACHED_PROVIDER
    if _CACHED_PROVIDER is not None:
        return _CACHED_PROVIDER
    provider = create_aster_instrument_provider(
        clock=clock,
        api_key=None,
        api_secret=None,
        config=config,
        proxy_url=proxy_url,
    )
    _CACHED_PROVIDER = provider
    return provider


class AsterLiveDataClientFactory(LiveDataClientFactory):
    """
    Provides an ASTERDEX live data client factory (Binance-futures compatible).
    """

    @staticmethod
    def create(  # type: ignore[override]
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: AsterDataClientConfig,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
    ) -> AsterMarketDataClient:
        provider = _get_cached_provider(clock=clock, proxy_url=config.proxy_url, config=config.instrument_provider)  # type: ignore[arg-type]
        return create_aster_market_data_client(
            loop=loop,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=provider,
            config=config,
            api_key=config.api_key,
            api_secret=config.api_secret,
            proxy_url=config.proxy_url,
            name=name,
        )


class AsterLiveExecClientFactory(LiveExecClientFactory):
    """
    Provides an ASTERDEX live execution client factory (Binance-futures compatible).
    """

    @staticmethod
    def create(  # type: ignore[override]
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: AsterExecClientConfig,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
    ) -> AsterExecutionClient:
        provider = _get_cached_provider(clock=clock, proxy_url=config.proxy_url, config=config.instrument_provider)  # type: ignore[arg-type]
        return create_aster_execution_client(
            loop=loop,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=provider,
            config=config,
            api_key=config.api_key,
            api_secret=config.api_secret,
            proxy_url=config.proxy_url,
            name=name,
        )
