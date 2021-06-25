import rx
import rx.operators as ops
import typing

import requests
from datetime import datetime
from decimal import Decimal

from ..context import Context
from ..market import Market
from ..observables import observable_pipeline_error_reporter
from ..oracle import Oracle, OracleProvider, OracleSource, Price, \
    SupportedOracleFeature
from mango.types_ import Configuration


class NoSuchOracleError(Exception):
    pass


class MSolOracle(Oracle):
    def __init__(self, market: Market, cfg: Configuration):
        name = "mSOL Oracle for mSOL/SOL"
        super().__init__(name, market)
        features: SupportedOracleFeature = SupportedOracleFeature.MID_PRICE
        self.cfg: Configuration = cfg
        self.source: OracleSource = OracleSource(
            "mSOL Oracle",
            name,
            features,
            market
        )

    def fetch_price(self, context: Context) -> Price:

        response = requests.get(self.cfg.account.marinade_api_url)
        price = Decimal(response.text)

        return Price(self.source, datetime.now(), self.market, price, price, price, 0)

    def to_streaming_observable(self, context: Context) -> rx.core.Observable:
        return rx.interval(1).pipe(
            ops.observe_on(context.pool_scheduler),
            ops.start_with(-1),
            ops.map(lambda _: self.fetch_price(context)),
            ops.catch(observable_pipeline_error_reporter),
            ops.retry(),
        )


class MSolOracleProvider(OracleProvider):
    def __init__(self, cfg: Configuration) -> None:
        super().__init__("mSOL Oracle Factory")
        self.cfg: Configuration = cfg

    def oracle_for_market(
            self,
            context: Context,
            market: Market
    ) -> typing.Optional[Oracle]:

        if market.symbol != "MSOL/SOL":
            raise NoSuchOracleError(f"No mSOL oracle for market {market.symbol}")

        return MSolOracle(market, self.cfg)

    def all_available_symbols(self, context: Context) -> typing.Sequence[str]:
        return ["MSOL/SOL"]
