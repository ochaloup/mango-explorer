# # ⚠ Warning
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING
# BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE
# AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
# DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#
# [🥭 Mango Markets](https://markets/) support is available at:
#   [Docs](https://docs.markets/)
#   [Discord](https://discord.gg/67jySBhxrg)
#   [Twitter](https://twitter.com/mangomarkets)
#   [Github](https://github.com/blockworks-foundation)
#   [Email](mailto:hello@blockworks.foundation)


import json
import logging
import requests
from requests.exceptions import ConnectionError
import re
import rx
import rx.operators as rxop
import typing

from datetime import datetime
from decimal import Decimal
from rx.subject import Subject
from rx.core import Observable
import cachetools.func

from mango import observable_pipeline_error_reporter

from ...context import Context
from ...market import Market
from ...observables import DisposePropagator, DisposeWrapper
from ...oracle import Oracle, OracleProvider, OracleSource, Price, SupportedOracleFeature
from ...reconnectingwebsocket import ReconnectingWebsocket
from mango.types_ import Configuration


LOGGER = logging.getLogger(__name__)


# # 🥭 FTX
#
# This file contains code specific to the [Ftx Network](https://ftx.com/).
#

def _ftx_get_all_from_url(url: str) -> typing.Dict:

    try:
        response = requests.get(url)
        response_values = response.json()

    except ConnectionError:
        LOGGER.info(f'Failed getting ftx data with {url}, ConnectionError.')
        return {}
    except json.decoder.JSONDecodeError:
        LOGGER.info(f'Failed getting ftx data with {url}, JSONDecodeError.')
        return {}

    return response_values


@cachetools.func.ttl_cache(maxsize=128, ttl=1)
def _ftx_get_all_from_url_cached(url: str) -> typing.Dict:
    return _ftx_get_all_from_url(url)


def _ftx_get_from_url(symbol: str) -> typing.Dict:
    # url = f"https://ftx.com/api/markets/{symbol}"
    source_uncached_url = "https://ftx.com/api/markets"
    url = "http://127.0.0.1:8082/api/markets"

    all_response_values = _ftx_get_all_from_url(url)
    if ("success" not in all_response_values) or (not all_response_values["success"]):
        LOGGER.info('Using uncached url to query ftx prices.')
        all_response_values = _ftx_get_all_from_url_cached(source_uncached_url)

    if ("success" not in all_response_values) or (not all_response_values["success"]):
        raise Exception(f"Failed to get from FTX URL: {url}/{symbol}")

    response_values = [r for r in all_response_values['result'] if r['name'] == symbol.upper()]

    if not response_values:
        raise Exception(
            f"Failed to get symbol {symbol} from FTX URL: {url}/{symbol} - {response_values}"
        )
    return response_values[0]


# # mSOL

MSOL_SYMBOLS = {'MSOL/USDC', 'MSOL/RAY'}
MSOL_INVERSE_SYMBOLS = {'ORCA/MSOL'}


def _get_msol_price_in_sol(url: str) -> Decimal:
    response = requests.get(url)
    return Decimal(response.text)


# # 🥭 FtxOracleConfidence constant
#
# FTX doesn't provide a confidence value.
#

FtxOracleConfidence: Decimal = Decimal(0)


# # 🥭 FtxOracle class
#
# Implements the `Oracle` abstract base class specialised to the Ftx Network.
#

class FtxOracle(Oracle):
    def __init__(self, market: Market, ftx_symbol: str, cfg: Configuration):
        name = f"Ftx Oracle for {market.symbol} / {ftx_symbol}"
        super().__init__(name, market)
        self.market: Market = market
        self.ftx_symbol: str = ftx_symbol
        self.cfg: Configuration = cfg
        features: SupportedOracleFeature\
            = SupportedOracleFeature.MID_PRICE | SupportedOracleFeature.TOP_BID_AND_OFFER
        self.source: OracleSource = OracleSource("FTX", name, features, market)

    def _fetch_price(self, context: Context, symbol) -> Price:

        result = _ftx_get_from_url(symbol)

        if self.market.symbol in MSOL_SYMBOLS:
            factor = _get_msol_price_in_sol(self.cfg.account.marinade_api_url)
        elif self.market.symbol in MSOL_INVERSE_SYMBOLS:
            factor = 1 / _get_msol_price_in_sol(self.cfg.account.marinade_api_url)
        else:
            factor = 1

        bid = Decimal(result["bid"]) * factor
        mid = Decimal(result["price"]) * factor
        ask = Decimal(result["ask"]) * factor

        return bid, mid, ask

    def fetch_price(self, context: Context) -> Price:

        if '//' not in self.ftx_symbol:
            bid, mid, ask = self._fetch_price(context, self.ftx_symbol)

        else:
            symbol_num, symbol_den = self.ftx_symbol.split('//')
            bid_num, mid_num, ask_num = self._fetch_price(context, symbol_num)
            bid_den, mid_den, ask_den = self._fetch_price(context, symbol_den)

            bid = bid_num / ask_den
            mid = mid_num / mid_den
            ask = ask_num / bid_den

        return Price(
            self.source, datetime.now(), self.market,
            bid, mid, ask,
            FtxOracleConfidence
        )

    def to_streaming_observable(self, context: Context) -> rx.core.Observable:
        subject = Subject()

        def _on_item(data):
            if data["type"] == "update":
                bid = Decimal(data["data"]["bid"])
                ask = Decimal(data["data"]["ask"])
                mid = (bid + ask) / Decimal(2)
                time = data["data"]["time"]
                timestamp = datetime.fromtimestamp(time)
                price = Price(
                    self.source,
                    timestamp,
                    self.market,
                    bid,
                    mid,
                    ask,
                    FtxOracleConfidence
                )
                subject.on_next(price)

        ws: ReconnectingWebsocket = ReconnectingWebsocket(
            "wss://ftx.com/ws/",
            lambda ws: ws.send(
                f"""{{"op": "subscribe", "channel": "ticker", "market":
                "{self.ftx_symbol}"}}"""
            )
        )
        ws.item.subscribe(on_next=_on_item)

        if context.reconnect_interval > 0:
            rx.interval(context.reconnect_interval).pipe(
                rxop.observe_on(context.pool_scheduler),
                rxop.catch(observable_pipeline_error_reporter),
                rxop.retry()
            ).subscribe(lambda x: ws.force_reconnect())

        def subscribe(observer, scheduler_=None):
            subject.subscribe(observer, scheduler_)

            disposable = DisposePropagator()
            disposable.add_disposable(DisposeWrapper(lambda: ws.close()))
            disposable.add_disposable(DisposeWrapper(lambda: subject.dispose()))

            return disposable

        price_observable = Observable(subscribe)

        ws.open()

        return price_observable


# # 🥭 FtxOracleProvider class
#
# Implements the `OracleProvider` abstract base class specialised to the Ftx Network.
#

class FtxOracleProvider(OracleProvider):
    def __init__(self, cfg: Configuration) -> None:
        super().__init__("Ftx Oracle Factory")
        self.cfg: Configuration = cfg

    def oracle_for_market(self, context: Context, market: Market) -> typing.Optional[Oracle]:
        symbol = self._market_symbol_to_ftx_symbol(market.symbol)
        return FtxOracle(market, symbol, self.cfg)

    def all_available_symbols(self, context: Context) -> typing.Sequence[str]:
        result = _ftx_get_from_url("https://ftx.com/api/markets")
        symbols: typing.List[str] = []
        for market in result:
            symbol: str = market["name"]
            if symbol.endswith("USD"):
                symbol = f"{symbol}C"
            symbols += [symbol]

        return symbols

    def _market_symbol_to_ftx_symbol(self, symbol: str) -> str:
        normalised = symbol.upper()
        fixed_usdc = re.sub("USDC$", "USD", normalised)
        fixed_perp = re.sub("\\-PERP$", "/USD", fixed_usdc)

        if normalised == 'MSOL/USDC':
            return 'SOL/USD'

        if normalised.endswith('/SOL') or normalised.endswith('/USDT'):
            first, second = normalised.split('/')
            return f'{first}/USD//{second}/USD'

        else:
            return fixed_perp
