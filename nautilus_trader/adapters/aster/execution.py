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

from nautilus_trader.adapters.aster.config import AsterExecClientConfig
from nautilus_trader.adapters.aster.constants import ASTER_BASE_URL_WS
from nautilus_trader.adapters.aster.providers import AsterInstrumentProvider
from nautilus_trader.adapters.binance.common.enums import BinanceAccountType
from nautilus_trader.adapters.binance.http.error import BinanceClientError
from nautilus_trader.adapters.binance.futures.execution import BinanceFuturesExecutionClient
from nautilus_trader.adapters.binance.http.client import BinanceHttpClient
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock
from nautilus_trader.common.component import MessageBus
from nautilus_trader.common.enums import LogColor


class AsterExecutionClient(BinanceFuturesExecutionClient):
    """
    Binance Futures execution client wired to ASTER endpoints/venue.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        client: BinanceHttpClient,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
        instrument_provider: AsterInstrumentProvider,
        config: AsterExecClientConfig,
        name: str | None = None,
    ) -> None:
        super().__init__(
            loop=loop,
            client=client,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=instrument_provider,
            base_url_ws=config.base_url_ws or ASTER_BASE_URL_WS,
            config=config,
            account_type=BinanceAccountType.USDT_FUTURES,
            name=name,
        )

    async def _init_dual_side_position(self) -> None:
        # ASTERDEX does not reliably support the Binance futures hedge-mode endpoint.
        # When unavailable, assume one-way mode (dual_side_position=False) and continue,
        # because this check is only used to guard reduce_only behavior.
        try:
            await super()._init_dual_side_position()
        except BinanceClientError as exc:
            self._is_dual_side_position = False
            self._log.warning(
                f"ASTERDEX hedge-mode check failed (status={exc.status}); assuming one-way mode. "
                "If you are running hedge mode on the exchange, disable it or set use_reduce_only=false.",
                LogColor.YELLOW,
            )
