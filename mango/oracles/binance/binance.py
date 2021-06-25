import logging
import requests
import rx
import time
import typing

from datetime import datetime
from decimal import Decimal
from rx.subject import Subject
from rx.core import Observable

from ...context import Context
from ...market import Market
from ...observables import DisposePropagator, DisposeWrapper
from ...oracle import Oracle, OracleProvider, OracleSource, Price, SupportedOracleFeature
from ...reconnectingwebsocket import ReconnectingWebsocket
from mango.types_ import Configuration


LOGGER = logging.getLogger(__name__)


# # 🥭 Binance
#
# This file contains code specific to the Binance CEX.
#


def _binance_get_from_url(symbol: str) -> typing.Dict:
    # This will have to be potentially cached on nginx level.
    url = f"https://api.binance.com/api/v3/ticker/bookTicker?symbol={symbol}"

    response = requests.get(url)
    response_values = response.json()

    if not response.ok:
        raise Exception(f"Failed to get from FTX URL: {url}/{symbol}")

    if not response_values:
        raise Exception(
            f"Failed to get symbol {symbol} from FTX URL: {url}/{symbol} - {response_values}"
        )
    return response_values


# # mSOL

MSOL_SYMBOLS = {'MSOL/USDC', 'MSOL/RAY'}
MSOL_INVERSE_SYMBOLS = {'ORCA/MSOL'}


def _get_msol_price_in_sol(url: str) -> Decimal:
    response = requests.get(url)
    return Decimal(response.text)


# # 🥭 BinanceOracleConfidence constant
#
# Binance doesn't provide a confidence value.
#

BinanceOracleConfidence: Decimal = Decimal(0)


# # 🥭 BinanceOracle class
#
# Implements the `Oracle` abstract base class specialised to the Binance CEX.
#

class BinanceOracle(Oracle):
    def __init__(self, market: Market, binance_symbol: str, cfg: Configuration):
        name = f"Binance Oracle for {market.symbol} / {binance_symbol}"
        super().__init__(name, market)
        self.market: Market = market
        self.binance_symbol: str = binance_symbol
        self.cfg: Configuration = cfg
        features: SupportedOracleFeature\
            = SupportedOracleFeature.MID_PRICE | SupportedOracleFeature.TOP_BID_AND_OFFER
        self.source: OracleSource = OracleSource("Binance", name, features, market)

    def _fetch_price(self, context: Context, symbol: str) -> Price:
        result = _binance_get_from_url(symbol)

        if self.market.symbol in MSOL_SYMBOLS:
            factor = _get_msol_price_in_sol(self.cfg.account.marinade_api_url)
        elif self.market.symbol in MSOL_INVERSE_SYMBOLS:
            factor = 1 / _get_msol_price_in_sol(self.cfg.account.marinade_api_url)
        else:
            factor = 1

        bid = Decimal(result["bidPrice"]) * factor
        ask = Decimal(result["askPrice"]) * factor
        mid = (bid + ask) / Decimal('2')

        return bid, mid, ask

    def fetch_price(self, context: Context) -> Price:
        if '//' not in self.binance_symbol:
            bid, mid, ask = self._fetch_price(context, self.binance_symbol)

        else:
            symbol_num, symbol_den = self.binance_symbol.split('//')
            bid_num, mid_num, ask_num = self._fetch_price(context, symbol_num)
            bid_den, mid_den, ask_den = self._fetch_price(context, symbol_den)

            bid = bid_num / ask_den
            mid = mid_num / mid_den
            ask = ask_num / bid_den

        return Price(
            self.source, datetime.now(), self.market,
            bid, mid, ask,
            BinanceOracleConfidence
        )

    def to_streaming_observable(self, _: Context) -> rx.core.Observable:
        """
        See binance websocket docs
        https://binance-docs.github.io/apidocs/spot/en/#live-subscribing-unsubscribing-to-streams
        """
        if '//' in self.binance_symbol:
            raise NotImplementedError('Synthetic symbols are not implemented yet.')

        subject = Subject()

        def _on_item(data):
            if 'error' not in data:
                bid = Decimal(data['b'])
                ask = Decimal(data['a'])
                mid = (bid + ask) / Decimal(2)
                time_ = time.time()
                timestamp = datetime.fromtimestamp(time_)
                price = Price(
                    self.source, timestamp, self.market, bid, mid, ask, BinanceOracleConfidence
                )
                self.logger.info(f'Received price: {price}')
                subject.on_next(price)

        ws: ReconnectingWebsocket = ReconnectingWebsocket(
            f'wss://stream.binance.com:9443/ws/{self.binance_symbol.lower()}@bookTicker',
            lambda ws: ws.send("")
        )
        ws.item.subscribe(on_next=_on_item)

        def subscribe(observer, scheduler_=None):
            subject.subscribe(observer, scheduler_)

            disposable = DisposePropagator()
            disposable.add_disposable(DisposeWrapper(lambda: ws.close()))
            disposable.add_disposable(DisposeWrapper(lambda: subject.dispose()))

            return disposable

        price_observable = Observable(subscribe)

        ws.open()

        return price_observable


# # 🥭 BinanceOracleProvider class
#
# Implements the `OracleProvider` abstract base class specialised to the Binance CEX.
#

class BinanceOracleProvider(OracleProvider):
    def __init__(self, cfg: Configuration) -> None:
        super().__init__("Binance Oracle Factory")
        self.cfg: Configuration = cfg

    def oracle_for_market(self, context: Context, market: Market) -> typing.Optional[Oracle]:
        symbol = self._market_symbol_to_binance_symbol(market.symbol)
        return BinanceOracle(market, symbol, self.cfg)

    @staticmethod
    def all_available_symbols(_: Context) -> typing.Sequence[str]:
        url = 'https://api.binance.com/api/v3/exchangeInfo'

        response = requests.get(url)
        response_values = response.json()
        return [symbol['symbol'] for symbol in response_values['symbols']]

    def _market_symbol_to_binance_symbol(self, symbol: str) -> str:
        symbol = symbol.upper()
        if '//' in symbol:
            splitted = symbol.split('//')
            if len(splitted) != 2:
                raise ValueError(f'Incorrect symbol (// only once is allowed): {symbol}')
            first, second = splitted
            return '//'.join([
                self._adjust_symbol_for_available_symbols(first.replace('/', '')),
                self._adjust_symbol_for_available_symbols(second.replace('/', ''))
            ])
        return self._adjust_symbol_for_available_symbols(symbol.replace('/', ''))

    def _adjust_symbol_for_available_symbols(self, symbol: str) -> str:
        # Sorry for the incorrect type "None", but something has to be there.
        all_symbols = self.all_available_symbols(None)
        if symbol in all_symbols:
            return symbol
        if symbol.replace('USDC', 'USDT') in all_symbols:
            return symbol.replace('USDC', 'USDT')
        if symbol.replace('USDT', 'USDC') in all_symbols:
            return symbol.replace('USDT', 'USDC')
        raise ValueError(f'Incorrect symbol for Binance oracle: {symbol}')
