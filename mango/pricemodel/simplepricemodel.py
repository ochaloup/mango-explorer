"""
Calculates simple combinations of prices.

"""

from typing import Dict
from decimal import Decimal
import logging

from mango import Price
from mango.types_ import MarketMakerConfiguration
from mango.modelstate import ModelState
from mango.modelstatevalues import ModelStateValues
from mango.marketmaking.valuemodel import ValueModel
from mango.marketmaking.ewma import EWMA


def calculate_aggregate_price(
        weights: Dict[str, Decimal],
        ewma_weight: Decimal,
        oracle_prices: Dict[str, Price],
        price_center_ewma: EWMA,
        prices_oracle_ewma: Dict[str, EWMA]
) -> Decimal:
    """
    Calculates
    result = alpha_1(FTX - beta(EWMA(FTX) - EWMA(PC))) + alpha_2(KRK - beta(EWMA(KRK) - EWMA(PC)) +
    """
    return sum(
        weights[source_name] * (
            price.mid_price - ewma_weight * (
                prices_oracle_ewma[source_name].latest - price_center_ewma.latest
            )
        )
        for source_name, price in oracle_prices.items()
    )


class FairPriceModel(ValueModel[MarketMakerConfiguration]):

    def __init__(self, cfg: MarketMakerConfiguration):

        self.logger = logging.getLogger(self.__class__.__name__)
        self.cfg = cfg

        self.price_params = dict(zip(cfg.oracle_providers, cfg.price_weights))
        self.pcd_coef = 1 - sum(cfg.price_weights)
        if self.pcd_coef > 1 or self.pcd_coef < 0:
            raise ValueError(
                'Incorrect values in cfg.price_weights. Their sum is not in [0,1] interval'
            )

        self.price_center_ewma = EWMA(cfg.ewma_halflife)
        self.prices_oracle_ewma = {
            provider: EWMA(cfg.ewma_halflife)
            for provider in cfg.oracle_providers
        }
        self.ewma_weight = cfg.ewma_weight

    def eval(self, model_state: ModelState):

        price_center = model_state.values.price_center

        self.price_center_ewma.update(price_center)
        self.logger.info(
            'price center is:',
            extra=dict(price_center=price_center, ewma_center=self.price_center_ewma.latest)
        )

        for source_name, price in model_state.prices.items():
            self.prices_oracle_ewma[source_name].update(price.mid_price)
        self.logger.info('Oracle prices:', extra=dict(
            oracle_prices={name: price.mid_price for name, price in model_state.prices.items()},
            oracle_prices_ewma={
                name: ewma.latest for name, ewma in self.prices_oracle_ewma.items()
            },
        ))

        price_aggregated = calculate_aggregate_price(
            weights=self.price_params,
            ewma_weight=self.ewma_weight,
            oracle_prices=model_state.prices,
            price_center_ewma=self.price_center_ewma,
            prices_oracle_ewma=self.prices_oracle_ewma,
        )
        self.logger.info('price aggregated is:', extra=dict(price_aggregated=price_aggregated))

        # Originally in the email thread we had
        # FP = EWMA(PC) + FTX - EWMA(FTX)
        # respectively
        # FP = alpha_1(FTX - (EWMA(FTX) - EWMA(PC))) + alpha_2(KRK - (EWMA(KRK) - EWMA(PC))
        fair_price = price_aggregated + self.pcd_coef * price_center

        # PA = price aggregated, PC = price center
        self.logger.info(
            'Current fair price consists of PC: %.4f and PA: %.4f with PC coef: %.4f',
            price_center, price_aggregated / (1 - self.pcd_coef), self.pcd_coef
        )

        return ModelStateValues(fair_price=fair_price)