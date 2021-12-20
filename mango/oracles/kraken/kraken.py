import logging
import requests
from requests.exceptions import ConnectionError
import re
import rx
import rx.operators as rxop
import time
import typing

from datetime import datetime
from decimal import Decimal
from rx.subject import Subject
from rx.core import Observable

from mango import observable_pipeline_error_reporter

from ...context import Context
from ...market import Market
from ...observables import DisposePropagator, DisposeWrapper
from ...oracle import Oracle, OracleProvider, OracleSource, Price, SupportedOracleFeature
from ...reconnectingwebsocket import ReconnectingWebsocket
from mango.types_ import Configuration


LOGGER = logging.getLogger(__name__)


# # 🥭 Kraken
#
# This file contains code specific to the Kraken CX.
#


def _kraken_get_symbol_from_url(url: str) -> typing.Dict:

    try:
        response = requests.get(url)
        response_values = response.json()

    except ConnectionError:
        return {}

    return response_values


def _kraken_get_from_url(symbol: str) -> typing.Dict:
    url = f'https://api.kraken.com/0/public/Depth?pair={symbol}'

    all_response_values = _kraken_get_symbol_from_url(url)

    if all_response_values.get('error'):
        raise Exception(f'Failed to get from Kraken URL: {url}')

    response_values = all_response_values['result']

    if not response_values:
        raise Exception(
            f'Failed to get symbol {symbol} from Kraken URL: {url} - {response_values}'
        )
    return response_values


# # mSOL

MSOL_SYMBOLS = {'MSOL/USDC', 'MSOL/RAY'}
MSOL_INVERSE_SYMBOLS = {'ORCA/MSOL'}


def _get_msol_price_in_sol(url: str) -> Decimal:
    response = requests.get(url)
    return Decimal(response.text)


# # 🥭 KrakenOracleConfidence constant
#
# Kraken doesn't provide a confidence value.
#

KrakenOracleConfidence: Decimal = Decimal(0)


# # 🥭 KrakenOracle class
#
# Implements the `Oracle` abstract base class specialised to the Kraken CEX.
#

class KrakenOracle(Oracle):
    def __init__(self, market: Market, kraken_symbol: str, cfg: Configuration):
        name = f"Kraken Oracle for {market.symbol} / {kraken_symbol}"
        super().__init__(name, market)
        self.market: Market = market
        self.kraken_symbol: str = kraken_symbol
        self.cfg: Configuration = cfg
        features: SupportedOracleFeature\
            = SupportedOracleFeature.MID_PRICE | SupportedOracleFeature.TOP_BID_AND_OFFER
        self.source: OracleSource = OracleSource("Kraken", name, features, market)

    def _fetch_price(self, context: Context, symbol) -> typing.Tuple[Decimal, Decimal, Decimal]:

        result = _kraken_get_from_url(symbol)

        if self.market.symbol in MSOL_SYMBOLS:
            factor = _get_msol_price_in_sol(self.cfg.solana.marinade_api_url)
        elif self.market.symbol in MSOL_INVERSE_SYMBOLS:
            factor = 1 / _get_msol_price_in_sol(self.cfg.solana.marinade_api_url)
        else:
            factor = 1

        bid = Decimal(result[symbol]['bids'][0][0]) * factor
        ask = Decimal(result[symbol]['asks'][0][0]) * factor
        mid = (bid + ask) / 2

        return bid, mid, ask

    def fetch_price(self, context: Context) -> Price:

        if '//' not in self.kraken_symbol:
            bid, mid, ask = self._fetch_price(context, self.kraken_symbol)

        else:
            symbol_num, symbol_den = self.kraken_symbol.split('//')
            bid_num, mid_num, ask_num = self._fetch_price(context, symbol_num)
            bid_den, mid_den, ask_den = self._fetch_price(context, symbol_den)

            bid = bid_num / ask_den
            mid = mid_num / mid_den
            ask = ask_num / bid_den

        return Price(
            self.source, datetime.now(), self.market,
            bid, mid, ask,
            KrakenOracleConfidence
        )

    def to_streaming_observable(self, context: Context) -> rx.core.Observable:
        subject = Subject()

        class SimpleBook:
            ASK_SIDES = {'a', 'as', 'ask'}
            BID_SIDES = {'b', 'bs', 'bid'}

            def __init__(self) -> None:
                self.bids: typing.List[Decimal] = []
                self.asks: typing.List[Decimal] = []

            def update_or_insert(self, side: str, price: Decimal) -> None:
                if side in self.ASK_SIDES:
                    self.asks = [
                        *[p for p in self.asks if p < price],
                        price,
                        *[p for p in self.asks if p > price]
                    ][:10]
                elif side in self.BID_SIDES:
                    self.bids = [
                        *[p for p in self.bids if p > price],
                        price,
                        *[p for p in self.bids if p < price]
                    ][:10]
                else:
                    raise ValueError(f'Incorrect side - {side}')

            def drop(self, side: str, price: Decimal) -> None:
                if side in self.ASK_SIDES:
                    self.asks = [p for p in self.asks if p != price]
                elif side in self.BID_SIDES:
                    self.bids = [p for p in self.bids if p != price]
                else:
                    raise ValueError(f'Incorrect side - {side}')

        simple_book = SimpleBook()

        def _on_item(data):
            if isinstance(data, list):
                # a and b can be in data or as and bs can be in data
                for side_key in ['a', 'b', 'as', 'bs']:
                    if side_key in data[1]:
                        for quote in data[1][side_key]:
                            quantity = Decimal(quote[1])
                            if quantity != Decimal('0'):
                                simple_book.update_or_insert(side_key, Decimal(quote[0]))
                            else:
                                simple_book.drop(side_key, Decimal(quote[0]))
                bid = None if not simple_book.bids else simple_book.bids[0]
                ask = None if not simple_book.asks else simple_book.asks[0]
                mid = None if bid is None or ask is None else (bid + ask) / Decimal(2)
                time_ = time.time()
                timestamp = datetime.fromtimestamp(time_)
                price = Price(
                    self.source,
                    timestamp,
                    self.market,
                    bid,
                    mid,
                    ask,
                    KrakenOracleConfidence
                )
                subject.on_next(price)

                self._check_quality_of_price_update(price, context)

        ws: ReconnectingWebsocket = ReconnectingWebsocket(
            "wss://ws.kraken.com/",
            lambda ws: ws.send(
                # The string has to be split this way because f string on {"name":"book"} failes
                '{"event":"subscribe", "subscription":{"name":"book"}, "pair":['\
                + f'"{self.kraken_symbol}"'\
                + "]}"
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


# # 🥭 KrakenOracleProvider class
#
# Implements the `OracleProvider` abstract base class specialised to the Kraken CEX.
#

class KrakenOracleProvider(OracleProvider):
    def __init__(self, cfg: Configuration) -> None:
        super().__init__("Kraken Oracle Factory")
        self.cfg: Configuration = cfg

    def oracle_for_market(self, context: Context, market: Market) -> typing.Optional[Oracle]:
        symbol = self._market_symbol_to_kraken_symbol(market.symbol)
        return KrakenOracle(market, symbol, self.cfg)

    def all_available_symbols(self, context: Context) -> typing.Sequence[str]:
        raise NotImplementedError()

    def _market_symbol_to_kraken_symbol(self, symbol: str) -> str:
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
