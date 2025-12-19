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
from asyncio import TaskGroup
from decimal import Decimal

from nautilus_trader.adapters.aster.config import AsterExecClientConfig
from nautilus_trader.adapters.aster.constants import ASTER_BASE_URL_WS
from nautilus_trader.adapters.aster.providers import AsterInstrumentProvider
from nautilus_trader.adapters.binance.common.enums import BinanceAccountType
from nautilus_trader.adapters.binance.http.error import BinanceClientError
from nautilus_trader.adapters.binance.futures.execution import BinanceFuturesExecutionClient
from nautilus_trader.adapters.binance.futures.http.account import BinanceFuturesAccountHttpAPI
from nautilus_trader.adapters.binance.futures.http.account import BinanceFuturesPositionRiskHttp
from nautilus_trader.adapters.binance.http.client import BinanceHttpClient
from nautilus_trader.accounting.accounts.margin import MarginAccount
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock
from nautilus_trader.common.component import MessageBus
from nautilus_trader.common.enums import LogColor
from nautilus_trader.core.datetime import millis_to_nanos


class AsterFuturesAccountHttpAPI(BinanceFuturesAccountHttpAPI):
    def __init__(
        self,
        client: BinanceHttpClient,
        clock: LiveClock,
        account_type: BinanceAccountType = BinanceAccountType.USDT_FUTURES,
    ) -> None:
        super().__init__(client=client, clock=clock, account_type=account_type)
        # ASTERDEX `/fapi/v3/positionRisk` uses a non-Binance auth scheme (nonce/user/signer),
        # but `/fapi/v2/positionRisk` is Binance-compatible. Force v2 here so ExecEngine
        # reconciliation can fetch positions reliably.
        if account_type == BinanceAccountType.USDT_FUTURES:
            self._endpoint_futures_position_risk = BinanceFuturesPositionRiskHttp(client, "/fapi/v2/")


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
        # ASTERDEX `/fapi/v3/positionRisk` uses a non-Binance auth scheme; use an account
        # HTTP API variant which forces `/fapi/v2/positionRisk` for reconciliation.
        self._futures_http_account = AsterFuturesAccountHttpAPI(client, clock, BinanceAccountType.USDT_FUTURES)
        self._http_account = self._futures_http_account

    async def _update_account_state(self) -> None:
        # Same as BinanceFuturesExecutionClient._update_account_state, but tolerate
        # missing/unsupported futures symbolConfig endpoint on ASTERDEX.
        account_info = await self._futures_http_account.query_futures_account_info(recv_window=str(5000))
        if account_info.canTrade:
            self._log.info("Binance API key authenticated", LogColor.GREEN)
            self._log.info(f"API key {self._http_client.api_key_masked} has trading permissions")
        else:
            self._log.error("Binance API key does not have trading permissions")
        self.generate_account_state(
            balances=account_info.parse_to_account_balances(),
            margins=account_info.parse_to_margin_balances(),
            reported=True,
            ts_event=millis_to_nanos(account_info.updateTime),
        )

        await self._await_account_registered(log_registered=False)

        if self._leverages:
            async with TaskGroup() as tg:
                leverage_tasks = [tg.create_task(self._futures_http_account.set_leverage(symbol, leverage)) for symbol, leverage in self._leverages.items()]
            for task in leverage_tasks:
                res = task.result()
                self._log.info(f"Set default leverage {res.symbol} {res.leverage}X")

        if self._margin_types:
            async with TaskGroup() as tg:
                margin_tasks = [
                    (tg.create_task(self._futures_http_account.set_margin_type(symbol, type_)), symbol, type_)
                    for symbol, type_ in self._margin_types.items()
                ]
            for _, symbol, type_ in margin_tasks:
                self._log.info(f"Set {symbol} margin type to {type_.value}")

        account: MarginAccount = self.get_account()
        try:
            symbol_configs = await self._futures_http_account.query_futures_symbol_config()
        except BinanceClientError as exc:
            self._log.warning(
                f"ASTERDEX symbolConfig endpoint unavailable (status={exc.status}); skipping leverage cache init.",
                LogColor.YELLOW,
            )
            return

        for config in symbol_configs:
            try:
                instrument_id = self._get_cached_instrument_id(config.symbol)
                leverage = Decimal(config.leverage)
                account.set_leverage(instrument_id, leverage)
                self._log.debug(f"Set leverage {config.symbol} {leverage}X")
            except KeyError:
                continue

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
