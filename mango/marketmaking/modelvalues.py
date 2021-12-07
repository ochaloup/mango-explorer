from typing import Sequence

import mango
from mango.types_ import MarketMakerConfiguration
from mango.pricemodel.simplepricemodel import FairPriceModel
from mango.marketmaking.valuemodel import ValueModel
from mango.modelstate import ModelState, ModelStateValues


def floor_quote(ratio, x, tol):
    """Increase ratio until there is something to quote."""

    size = ratio * x
    if size < tol:

        if x < tol or ratio < 1e-18:
            return 0

        return tol

    return size


class BestQuotePriceModel(ValueModel[MarketMakerConfiguration]):
    def eval(self, model_state: ModelState) -> ModelStateValues:

        fair_price = model_state.values.fair_price

        bid = fair_price * (1 - self.cfg.spread_ratio)
        ask = fair_price * (1 + self.cfg.spread_ratio)

        self.logger.info(
            'Quote prices bid: %.4f, fair: %.4f, ask: %.4f',
            bid,
            fair_price,
            ask,
        )

        return ModelStateValues(
            best_quote_price_bid=bid,
            best_quote_price_ask=ask
        )


class BestQuoteQuantityModel(ValueModel[MarketMakerConfiguration]):

    def __init__(self, cfg: MarketMakerConfiguration, is_perp: bool):
        super().__init__(cfg)
        self.is_perp = is_perp

    def eval(self, model_state: ModelState) -> ModelStateValues:

        base_tokens: mango.InstrumentValue = model_state.inventory.base
        quote_tokens: mango.InstrumentValue = model_state.inventory.quote

        fair_price = model_state.values.fair_price
        existing_orders = model_state.values.existing_orders

        self.logger.info(
            'Existing orders: %s',
            [order for order in existing_orders]
        )
        self.logger.info(
            'Balance base_tokens: %.4f, quote_tokens: %.4f',
            base_tokens.value, quote_tokens.value
        )

        if self.is_perp:
            position_base = base_tokens.value
            position_quote = -base_tokens.value
            total_available = quote_tokens.value / fair_price

        else:
            position_base = base_tokens.value + sum([
                order.quantity
                for order in existing_orders if order.side == mango.Side.SELL
            ])
            position_quote = quote_tokens.value / fair_price + sum([
                order.quantity
                for order in existing_orders if order.side == mango.Side.BUY
            ])
            total_available = position_base + position_quote

        leveraged_available = (self.cfg.leverage - 1) * total_available

        self.logger.info(
            'Inventory position_base: %.4f, '
            'position_quote: %.4f, '
            'leveraged_available: %.4f',
            position_base, position_quote, leveraged_available
        )

        # In case of SOL/USDC, if we have enough quote token (USDC), we want to
        # exchange it for SOL -> we want to quote bid(buy).  And vise versa.

        buy = floor_quote(
            self.cfg.position_size_ratios[0],
            leveraged_available + position_quote,
            self.cfg.min_quote_size
        )

        sell = floor_quote(
            self.cfg.position_size_ratios[1],
            leveraged_available + position_base,
            self.cfg.min_quote_size
        )

        return ModelStateValues(
            best_quantity_buy=buy,
            best_quantity_sell=sell
        )


# TODO: Not completely conformant - will be after we remove existing_orders
class ModelValuesGraph:

    def __init__(self, cfg: MarketMakerConfiguration, is_perp: bool):
        self.fair_price_model = FairPriceModel(cfg)
        self.best_price_model = BestQuotePriceModel(cfg)
        self.best_quantity_model = BestQuoteQuantityModel(cfg, is_perp)

    def update_values(
            self,
            model_state: ModelState,
            existing_orders: Sequence[mango.Order]
    ):

        # TODO: Move existing_orders into model_state !!
        model_state.values.existing_orders = existing_orders

        model_state.values.update(self.fair_price_model.eval(model_state))
        model_state.values.update(self.best_price_model.eval(model_state))
        model_state.values.update(self.best_quantity_model.eval(model_state))
