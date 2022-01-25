from typing import List, Sequence, Tuple
from decimal import Decimal
import logging

from solana.publickey import PublicKey

from mango.types_ import MarketMakerConfiguration
from mango.marketmaking.valuemodel import ValueModel
from mango.modelstate import ModelState, ModelStateValues
from mango import Order


class BookModel(ValueModel[MarketMakerConfiguration]):
    def eval(self, model_state: ModelState):

        limit = self.cfg.price_center_volume
        cutoff = self.cfg.book_quote_cutoff

        bid_sum_price = 0
        bid_sum_quantity = 0
        for bid in model_state.bids():

            if bid.owner == model_state.order_owner:
                continue

            regular_quantity = min(bid.quantity, cutoff)
            quantity = max(0, min(regular_quantity, limit - bid_sum_quantity))
            bid_sum_price += quantity * bid.price
            bid_sum_quantity += quantity

            if bid_sum_quantity >= limit:
                break

        ask_sum_price = 0
        ask_sum_quantity = 0
        for ask in model_state.asks():

            if ask.owner == model_state.order_owner:
                continue

            regular_quantity = min(ask.quantity, cutoff)
            quantity = max(0, min(regular_quantity, limit - ask_sum_quantity))
            ask_sum_price += quantity * ask.price
            ask_sum_quantity += quantity

            if ask_sum_quantity >= limit:
                break

        sum_quantity = bid_sum_quantity + ask_sum_quantity
        price_center = (ask_sum_price + bid_sum_price) / sum_quantity
        side_difference = (ask_sum_price - bid_sum_price) / sum_quantity
        book_spread = side_difference / price_center

        self.logger.info(
            'eval() book state: bid: %.4f, center: %.4f, ask: %.4f',
            model_state.top_bid.price,
            price_center,
            model_state.top_ask.price,
        )

        log_important_metrics(model_state.orderbook.bids, model_state.orderbook.asks, self.logger)

        self.logger.info(
            'eval()',
            extra=dict(
                sum_quantity=sum_quantity,
                price_center=price_center,
                side_difference=side_difference,
                book_spread=book_spread,
            )
        )

        return ModelStateValues(
            price_center=price_center,
            book_spread=book_spread,
        )


def log_important_metrics(
    bids: Sequence[Order],
    asks: Sequence[Order],
    logger: logging.Logger,
    n: int = 10,
) -> Tuple[List[Tuple[Decimal, Decimal]]]:
    """
    Returns aggregated orderbook sides of first n levels.
    return aggregated_bids, aggregated_asks
    """
    aggregated_asks = []
    aggregated_bids = []

    price = None
    quantity = 0
    for ask_order in asks:
        if price is None:
            price = ask_order.price

        if price != ask_order.price:
            # finish price level
            aggregated_asks.append((price, quantity))
            price = None
            quantity = 0
        else:
            quantity += ask_order.quantity

        if len(aggregated_asks) >= n:
            break

    price = None
    quantity = 0
    for bid_order in bids:
        if price is None:
            price = bid_order.price

        if price != bid_order.price:
            # finish price level
            aggregated_bids.append((price, quantity))
            price = None
            quantity = 0
        else:
            quantity += bid_order.quantity

        if len(aggregated_bids) >= n:
            break

    logger.info('Orderbook current state: bid: %s, ask: %s', aggregated_bids, aggregated_asks)

    big_order_MM = PublicKey('4qoYohoLH69gG8mp1Wk2hkKPN5NnfX7BHZYZFC359eva')
    logger.info(
        '4qoYohoLH69gG8mp1Wk2hkKPN5NnfX7BHZYZFC359eva and its quotes: bids: %s, asks: %s',
        [order for order in bids[:50] if order.owner == big_order_MM],
        [order for order in asks[:50] if order.owner == big_order_MM]
    )
