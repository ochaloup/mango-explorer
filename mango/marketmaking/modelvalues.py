from typing import Sequence

import mango
from mango.types_ import MarketMakerConfiguration
from mango.pricemodel.simplepricemodel import FairPriceModel
from mango.marketmaking.bookmodel import BookModel
from mango.marketmaking.spreadmodel import FairSpreadModel
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


class PositionModel(ValueModel[MarketMakerConfiguration]):

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

        return ModelStateValues(
            position_base=position_base,
            position_quote=position_quote,
            total_available=total_available,
            leveraged_available=leveraged_available
        )


class BestQuotePriceModel(ValueModel[MarketMakerConfiguration]):
    def eval(self, model_state: ModelState) -> ModelStateValues:

        fair_price = model_state.values.fair_price
        fair_spread = model_state.values.fair_spread

        bid = fair_price * (1 - fair_spread)
        ask = fair_price * (1 + fair_spread)

        self.logger.info(
            'Quote prices: bid: %.4f, fair: %.4f, ask: %.4f',
            bid,
            fair_price,
            ask,
        )

        return ModelStateValues(
            best_quote_price_bid=bid,
            best_quote_price_ask=ask,
        )


class HedgePriceBiasModel(ValueModel[MarketMakerConfiguration]):
    def eval(self, model_state: ModelState) -> ModelStateValues:

        bias_factor = self.cfg.hedge_price_bias_factor

        position_base = model_state.values.position_base
        position_quote = model_state.values.position_quote
        leveraged_available = model_state.values.leveraged_available

        # only ever tighten the spread_ratio because of position, never enlarge it
        bid_bias = 1 + max(0, bias_factor * position_quote / leveraged_available)
        ask_bias = 1 - max(0, bias_factor * position_base / leveraged_available)

        self.logger.info(
            'Hedge quote price bias: bid: %.4f, ask: %.4f',
            bid_bias - 1,
            ask_bias - 1,
        )

        return ModelStateValues(
            hedge_price_bias_bid=bid_bias,
            hedge_price_bias_ask=ask_bias,
        )


class BestQuoteQuantityModel(ValueModel[MarketMakerConfiguration]):
    def eval(self, model_state: ModelState) -> ModelStateValues:

        position_base = model_state.values.position_base
        position_quote = model_state.values.position_quote
        leveraged_available = model_state.values.leveraged_available

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


# TODO (Nov 2021) Not completely conformant - will be after we remove existing_orders
class ModelValuesGraph:

    def __init__(self, cfg: MarketMakerConfiguration, is_perp: bool):
        self.book_model = BookModel(cfg)
        self.position_model = PositionModel(cfg, is_perp)
        self.fair_spread_model = FairSpreadModel(cfg)
        self.fair_price_model = FairPriceModel(cfg)
        self.best_price_model = BestQuotePriceModel(cfg)
        self.hedge_price_bias_model = HedgePriceBiasModel(cfg)
        self.best_quantity_model = BestQuoteQuantityModel(cfg)

    def update_values(
            self,
            model_state: ModelState,
            existing_orders: Sequence[mango.Order]
    ):

        # TODO (Dec 2021): Move existing_orders into model_state !!
        model_state.values.existing_orders = existing_orders

        model_state.values.update(self.book_model.eval(model_state))
        model_state.values.update(self.fair_price_model.eval(model_state))
        model_state.values.update(self.position_model.eval(model_state))
        model_state.values.update(self.fair_spread_model.eval(model_state))
        model_state.values.update(self.best_price_model.eval(model_state))
        model_state.values.update(self.hedge_price_bias_model.eval(model_state))
        model_state.values.update(self.best_quantity_model.eval(model_state))
