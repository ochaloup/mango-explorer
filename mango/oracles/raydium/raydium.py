import logging
import requests
import typing

from time import time_ns
from datetime import datetime
from decimal import Decimal

from ...context import Context
from ...market import Market


class RaydiumConnectionError(Exception):
    pass


LOGGER = logging.getLogger()


def _get_from_url(url: str) -> typing.Dict:
    response = requests.get(url)
    if response.status_code == 500:
        # Raydium internal problems
        raise RaydiumConnectionError(f'Failed querying {url}')
    response_values = response.json()
    if ("success" not in response_values) or (not response_values["success"]):
        raise Exception(f"Failed to get from RAYDIUM URL: {url} - {response_values}")
    return response_values["data"]


class Trade():

    def __init__(
        self,
        source: str,
        timestamp: datetime,
        market: Market,
        price: Decimal,
        size: Decimal,
        side: str
    ) -> None:
        self.source = source
        self.timestamp = timestamp
        self.market = market
        self.price = price
        self.size = size
        self.side = side

        self.chainkeepers_timestamp: int = time_ns()

    def __dict__(self) -> typing.Dict[str, str]:
        return {
            'source': str(self.source),
            'timestamp': str(self.timestamp),
            'chainkeepers_timestamp': str(self.chainkeepers_timestamp),
            'market': str(self.market),
            'price': str(self.price),
            'size': str(self.size),
            'side': self.side
        }


class RaydiumTradeCollector():
    """
    Collects last trade... not oracle price, not mid price... last price!!!
    """

    def __init__(self, market: Market, raydium_symbol: str):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.name = f"Raydium Trade collector for {market.symbol} / {raydium_symbol}"
        self.market = market

        self.market: Market = market
        self.raydium_symbol: str = raydium_symbol

        # in milliseconds
        self._last_batch_fetched_price_timestamp = 0

    def fetch_price(self, _: Context) -> Trade:
        result = _get_from_url(
            f"https://api.raydium.io/trade/address?market={self.raydium_symbol}"
        )

        return self._process_trade(result[-1])

    def _process_trade(self, trade: typing.Dict[str, typing.Any]) -> Trade:

        return Trade(
            source=self.name,
            timestamp=datetime.utcfromtimestamp(trade['time'] / 1000),
            market=self.market,
            price=Decimal(trade['price']),
            size=Decimal(trade["size"]),
            side=trade['side']
        )

    def batch_fetch_prices(self, _: Context) -> typing.List[Trade]:
        """
        Returns list of all trades that happened after
        self._last_batch_fetched_price_timestamp.

        In case there were too many trades between "now" and last fetch,
        we will be missing some of them.
        """
        self.logger.debug(f'Getting prices for {self.name}')
        result = _get_from_url(
            f"https://api.raydium.io/trade/address?market={self.raydium_symbol}"
        )

        prices = [
            self._process_trade(trade)
            for trade in result
            if trade["time"] > self._last_batch_fetched_price_timestamp
        ]

        self._last_batch_fetched_price_timestamp = result[-1]["time"]

        return prices


class RaydiumTradeCollectorProvider():
    def __init__(self) -> None:
        self.name = "Raydium Trade Collector Factory"

    def trade_collector_for_market(
        self,
        context: Context,
        market: Market
    ) -> typing.Optional[RaydiumTradeCollector]:
        symbol = self._market_symbol_to_raydium_symbol(market.symbol)
        return RaydiumTradeCollector(market, symbol)

    def all_available_symbols(self, context: Context) -> typing.Sequence[str]:
        raise NotImplementedError(
            "RaydiumTradeCollectorProvider.all_available_symbols() is not implemented."
        )

    def _market_symbol_to_raydium_symbol(self, symbol: str) -> str:
        symbols = {
            "MNDE-mSOL": "AVxdeGgihchiKrhWne5xyUJj7bV2ohACkQFXMAtpMetx",
            "SOL-USDC": "9wFFyRfZBsuAha4YcuxcXLKwMxJR43S7fPfQLusDBzvT",
            "xCOPE-USDC": "7MpMwArporUHEGW7quUpkPZp5L5cHPs9eKUfKCdaPHq2",
            "ETH-SRM": "3Dpu2kXk87mF9Ls9caWCHqyBiv9gK3PwQkSvnrHZDrmi",
            "SOL-USDC": "9wFFyRfZBsuAha4YcuxcXLKwMxJR43S7fPfQLusDBzvT",
            "stSOL-USDC": "5F7LGsP1LPtaRV7vVKgxwNYX4Vf22xvuzyXjyar7jJqp",
            "mSOL-RAY": "HVFpsSP4QsC8gFfsFWwYcdmvt3FepDRB6xdFK2pSQtMr",
            "BTC-USDC": "A8YFbxQYFVqKZaoYJLLUVcQiWP7G2MeEgW5wsAQgMvFw",
            "RAY-USDC": "2xiv8A5xrJ7RnGdxXB42uFEkYHJjszEhaJyKKt4WaLep",
            "USDT-USDC": "77quYg4MGneUdjgXCunt9GgM1usmrxKY31twEy3WHwcS",
            "SOL-USDT": "HWHvQhFmJB3NUcu1aihKmrKegfVxBEHzwVX6yZCKEsi1",
            "RAY-ETH": "6jx6aoNFbmorwyncVP5V5ESKfuFc9oUYebob1iF6tgN4",
            "SRM-USDC": "ByRys5tuUWDgL73G8JBAEfkdFf8JWBzPBDHsBVQ5vbQA",
            "ETH-SOL": "HkLEttvwk2b4QDAHzNcVtxsvBG35L1gmYY4pecF9LrFe",
            "SRM-USDT": "AtNnsY1AyRERWJ8xCskfz38YdvruWVJQUVXgScC1iPb",
            "BTC-USDT": "C1EuT9VokAKLiW7i2ASnZUvxDoKuKkCpDDeNxAptuNe4",
            "ETH-USDC": "4tSvZvnbyzHXLMTiFonMyxZoHmFqau1XArcRCVHLZ5gX",
            "RAY-SOL": "C6tp2RVZnxBPFbnAsfTjis8BN9tycESAT4SgDQgbbrsA",
            "COPE-USDC": "6fc7v3PmjZG9Lk2XTot6BywGyYLkBQuzuFKd4FpCsPxk",
            "RAY-USDT": "teE55QrL4a4QSfydR9dnHF97jgCfptpuigbb53Lo95g",
            "BTC-SRM": "HfsedaWauvDaLPm6rwgMc6D5QRmhr8siqGtS6tf2wthU",
            "LARIX-RAY": "5GH4F2Z9adqkEP8FtR4sJqvrVgBuUSrWoQAa7bVCdB44",
            "mSOL-SOL": "5cLrMai1DsLRYc1Nio9qMTicsWtvzjzZfJPXyAoF4t1Z",
            "SRM-SOL": "jyei9Fpj2GtHLDDGgcuhDacxYLLiSyxU4TY7KxB2xai",
            "RAY-SRM": "Cm4MmknScg7qbKqytb1mM92xgDxv3TNXos4tKbBqTDy7",
            "ETH-USDT": "7dLVkUfBVfCGkFhSXDCq1ukM9usathSgS716t643iFGF",
            "SOL-SDC": "89pBeyUxduWdboHHShqwWavCrnckZu4SUPg7MZo1H6Na",
            "mSOL-USDC": "6oGsL2puUgySccKzn9XA9afqF217LfxP5ocq4B3LWsjy"
        }

        if symbol not in symbols:
            raise ValueError('Incorrect symbol.')
        else:
            return symbols[symbol]
