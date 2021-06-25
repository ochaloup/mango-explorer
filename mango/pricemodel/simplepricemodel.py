"""
Calculates simple combinations of prices.

"""

from typing import Dict
from decimal import Decimal
import logging

from mango.types_ import Configuration
from mango.marketmaking.modelstate import ModelState, ModelStateValues
from mango.marketmaking.valuemodel import ValueModel


def calculate_aggregate_price(
        weights: Dict[str, Decimal],
        model_state: ModelState
) -> Decimal:
    return sum(
        price.mid_price * weights[source_name]
        for source_name, price in model_state.prices.items()
    )


def compute_pcd(limit: Decimal, model_state: ModelState):

    bid_sum_price = 0
    bid_sum_quantity = 0
    for bid in reversed(model_state.bids):

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

    price_center = (bid_sum_price + ask_sum_price) / (2 * limit)

    return price_center


class FairPriceModel(ValueModel[Configuration]):

    def __init__(self, cfg: Configuration):

        self.logger = logging.getLogger(self.__class__.__name__)
        self.cfg = cfg

        self.price_params = dict(zip(cfg.oracle_providers, cfg.price_weights))
        self.pcd_coef = 1 - sum(cfg.price_weights)

    def eval(self, model_state: ModelState):

        price_aggregated = calculate_aggregate_price(
            self.price_params,
            model_state
        )

        price_center = compute_pcd(self.cfg.price_center_volume, model_state)

        fair_price = price_aggregated + self.pcd_coef * price_center

        self.logger.info('Current aggregated price: %.4f', price_aggregated)
        self.logger.info(
            'Book prices bid: %.4f, center: %.4f, ask: %.4f',
            model_state.top_bid.price,
            price_center,
            model_state.top_ask.price,
        )

        return ModelStateValues(fair_price=fair_price)
