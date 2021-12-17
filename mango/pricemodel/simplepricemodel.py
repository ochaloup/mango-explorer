"""
Calculates simple combinations of prices.

"""

from typing import Dict
from decimal import Decimal
import logging

from mango import Price
from mango.types_ import Configuration
from mango.modelstate import ModelState, ModelStateValues
from mango.marketmaking.valuemodel import ValueModel
from mango.marketmaking.ewma import EWMA


def calculate_aggregate_price(
        weights: Dict[str, Decimal],
        oracle_prices: Dict[str, Price],
        price_center_ewma: EWMA,
        prices_oracle_ewma: Dict[str, EWMA]
) -> Decimal:
    """
    Calculates
    result = alpha_1(FTX - (EWMA(FTX) - EWMA(PC))) + alpha_2(KRK - (EWMA(KRK) - EWMA(PC)) +
    """
    return sum(
        weights[source_name] * (
            price.mid_price - (prices_oracle_ewma[source_name].latest - price_center_ewma.latest)
        )
        for source_name, price in oracle_prices.items()
    )


def compute_pcd(limit: Decimal, model_state: ModelState):

    bid_sum_price = 0
    bid_sum_quantity = 0
    for bid in model_state.bids:

        quantity = max(0, min(bid.quantity, limit - bid_sum_quantity))
        bid_sum_price += quantity * bid.price
        bid_sum_quantity += quantity

        if bid_sum_quantity >= limit:
            break

    ask_sum_price = 0
    ask_sum_quantity = 0
    for ask in model_state.asks:

        quantity = max(0, min(ask.quantity, limit - ask_sum_quantity))
        ask_sum_price += quantity * ask.price
        ask_sum_quantity += quantity

        if ask_sum_quantity >= limit:
            break

    price_center = (bid_sum_price + ask_sum_price) / (bid_sum_quantity + ask_sum_quantity)

    return price_center


class FairPriceModel(ValueModel[Configuration]):

    def __init__(self, cfg: Configuration):

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

    def eval(self, model_state: ModelState):
        price_center = compute_pcd(self.cfg.price_center_volume, model_state)
        self.price_center_ewma.update(price_center)

        for source_name, price in model_state.prices.items():
            self.prices_oracle_ewma[source_name].update(price.mid_price)

        price_aggregated = calculate_aggregate_price(
            weights=self.price_params,
            oracle_prices=model_state.prices,
            price_center_ewma=self.price_center_ewma,
            prices_oracle_ewma=self.prices_oracle_ewma,
        )

        # Originally in the email thread we had
        # FP = EWMA(PC) + FTX - EWMA(FTX)
        # respectively
        # FP = alpha_1(FTX - (EWMA(FTX) - EWMA(PC))) + alpha_2(KRK - (EWMA(KRK) - EWMA(PC))
        fair_price = price_aggregated + self.pcd_coef * price_center

        # PA = price aggregated, PC = price center
        self.logger.info(
            'Current fair price consists of PC: %.4f and PA: %.4f with PC coef: %.4f',
            price_center, price_aggregated, self.pcd_coef
        )
        self.logger.info(
            'Book prices bid: %.4f, center: %.4f, ask: %.4f',
            model_state.top_bid.price,
            price_center,
            model_state.top_ask.price,
        )

        return ModelStateValues(fair_price=fair_price)
