import typing
from decimal import Decimal

import mango
from mango.modelstate import ModelState
from mango.types_ import MarketMakerConfiguration
from mango.marketmaking.orderchain.element import Element


class LeveragedFixedRatiosElement(Element):
    """Quotes are placed at a symmetrical spread ratio around fair price.

    The spread ratio is

       max(spread_ratio, book_spread_coef * book_spread)

    The size of the quotes is

       position_size_ratio ((leverage - 1) bankroll + position)

    position can be negative
    bankroll is the sum of positions, i.e. how much funds do we have on the account
    position_size_ratio can be different for bid and ask
    index 0 is for bid, index 1 for ask.

    For the side we have position on, only a hedging quote is placed getting rid
    of that position.  The quote is moved by multiplying with hedge_price_bias.

    """

    def __init__(
            self,
            cfg: MarketMakerConfiguration,
            is_perp: bool,
            order_type: mango.OrderType = mango.OrderType.POST_ONLY,
    ):

        """
        :param is_perp: If True placed orders are not added to available inventory.
        """

        super().__init__()

        self.cfg = cfg
        self.is_perp = is_perp
        self.order_type = order_type

    def process(
            self,
            context: mango.Context,
            model_state: ModelState,
            orders: typing.Sequence[mango.Order],
    ) -> typing.Sequence[mango.Order]:

        new_orders: typing.Sequence[mango.Order] = []

        min_quote_size = self.cfg.min_quote_size
        bias_factor = self.cfg.hedge_price_bias_factor

        position_base = model_state.values.position_base
        position_quote = model_state.values.position_quote

        best_quantity_buy = model_state.values.best_quantity_buy
        best_quantity_sell = model_state.values.best_quantity_sell

        best_quote_price_bid = model_state.values.best_quote_price_bid
        best_quote_price_ask = model_state.values.best_quote_price_ask

        hedge_price_bias_bid = model_state.values.hedge_price_bias_bid
        hedge_price_bias_ask = model_state.values.hedge_price_bias_ask

        if bias_factor > 0 and position_quote >= min_quote_size:
            new_orders.append(
                mango.Order.from_basic_info(
                    mango.Side.BUY,
                    price=hedge_price_bias_bid * best_quote_price_bid,
                    quantity=position_quote,
                    order_type=self.order_type
                )
            )

        if bias_factor <= 0 or position_quote < min_quote_size:
            if best_quantity_buy >= min_quote_size:
                new_orders.append(
                    mango.Order.from_basic_info(
                        mango.Side.BUY,
                        price=best_quote_price_bid,
                        quantity=best_quantity_buy,
                        order_type=self.order_type
                    )
                )

        if bias_factor > 0 and position_base >= min_quote_size:
            new_orders.append(
                mango.Order.from_basic_info(
                    mango.Side.SELL,
                    price=hedge_price_bias_ask * best_quote_price_ask,
                    quantity=position_base,
                    order_type=self.order_type
                )
            )

        if bias_factor <= 0 or position_base < min_quote_size:
            if best_quantity_sell >= min_quote_size:
                new_orders.append(
                    mango.Order.from_basic_info(
                        mango.Side.SELL,
                        price=best_quote_price_ask,
                        quantity=best_quantity_sell,
                        order_type=self.order_type
                    )
                )

        return new_orders

    def __str__(self) -> str:
        return f"{self.__class__.__name__}(order_type={self.order_type})"


class LimitSpreadNarrowingElement(Element):

    """
    May modifiy an `Order`s price if it would result in quoting inside spread.
    Quoting inside spread is more risky, so do it more gradualy.

      PKB' = PB + spread_narrowing_coef (PKB - PB),

    where PKB' is the price of the new quote inside spread, PB is best BID and
    PKB is the original suggested price for the quote.  Mirror for ASK.

    On top of this, chop prices so that we never BUY higher or SELL lower than
    fair price, i.e.

      PKB'' = min(fair_price, PKB')

    """

    def __init__(self, cfg: MarketMakerConfiguration):
        super().__init__()
        self.cfg = cfg

    def process(
            self,
            context: mango.Context,
            model_state: ModelState,
            orders: typing.Sequence[mango.Order]
    ) -> typing.Sequence[mango.Order]:

        coef = self.cfg.spread_narrowing_coef
        min_ratio = self.cfg.min_price_increment_ratio
        fair_price = model_state.values.fair_price
        order_owner = model_state.order_owner

        their_bids = [
            order
            for order in model_state.bids()
            if order.owner != order_owner
        ]
        if their_bids:
            top_bid = their_bids[0]
        else:
            top_bid = None

        their_asks = [
            order
            for order in model_state.asks()
            if order.owner != order_owner
        ]
        if their_asks:
            top_ask = their_asks[0]
        else:
            top_ask = None

        new_orders: typing.List[mango.Order] = []
        for order in orders:

            if (
                    order.side == mango.Side.BUY
                    and top_bid is not None  # noqa: W503
                    and top_ask is not None  # noqa: W503
                    and order.price >= top_bid.price  # noqa: W503
            ):

                price_increment = max(
                    coef * (order.price - top_bid.price),
                    min_ratio * top_bid.price
                )
                new_buy_price: Decimal = min(
                    top_bid.price + price_increment,
                    fair_price
                )
                new_buy: mango.Order = order.with_price(new_buy_price)
                self._logger.info(
                    f"""Order change - would tighten spread {top_bid.price if top_bid else None} / {top_ask.price}:
                Old: {order}
                New: {new_buy}""")
                new_orders.append(new_buy)

            elif (
                    order.side == mango.Side.SELL
                    and top_bid is not None  # noqa: W503
                    and top_ask is not None  # noqa: W503
                    and order.price <= top_ask.price  # noqa: W503
            ):
                price_increment = max(
                    coef * (top_ask.price - order.price),
                    min_ratio * top_ask.price
                )
                new_sell_price: Decimal = max(
                    top_ask.price - price_increment,
                    fair_price
                )
                new_sell: mango.Order = order.with_price(new_sell_price)
                self._logger.info(
                    f"""Order change - would tighten spread {top_bid.price} / {top_ask.price if top_ask else None}:
                Old: {order}
                New: {new_sell}""")

                new_orders.append(new_sell)

            else:
                # All OK with current order
                new_orders.append(order)

        return new_orders

    def __str__(self) -> str:
        return self.__class__.__name__


def is_shallow(
        cfg: MarketMakerConfiguration,
        model_state: mango.ModelState,
        order: mango.Order
) -> bool:
    """
    is_shallow is True if there is less quantity in front of order than cfg.max_order_depth.

    This does not take into account how much quantity is behind the order.
    """

    accumulated_quantity = Decimal(0)
    max_depth = cfg.max_order_depth
    cutoff = cfg.book_quote_cutoff

    if order.side == mango.Side.BUY:
        for bid_order in model_state.bids():

            if bid_order.price < order.price:
                return True

            else:
                accumulated_quantity += min(bid_order.quantity, cutoff)
                if accumulated_quantity >= max_depth:
                    return False

    elif order.side == mango.Side.SELL:
        for ask_order in model_state.asks():

            if ask_order.price > order.price:
                return True

            else:
                accumulated_quantity += min(ask_order.quantity, cutoff)
                if accumulated_quantity >= max_depth:
                    return False

    return False


class ShalowOrdersOnlyElement(Element):

    """Cancels all orders that would be quoted deeper than depth."""

    def __init__(self, cfg: MarketMakerConfiguration) -> None:
        super().__init__()
        self.cfg = cfg

    def process(
            self,
            context: mango.Context,
            model_state: ModelState,
            orders: typing.Sequence[mango.Order]
    ) -> typing.Sequence[mango.Order]:

        new_orders: typing.List[mango.Order] = []
        for order in orders:
            if is_shallow(self.cfg, model_state, order):
                new_orders.append(order)
            else:
                self._logger.info(f"Order change - order too deep, removing {order}")

        return new_orders

    def __str__(self) -> str:
        return self.__class__.__name__


class PreventCrossingElement(Element):

    """
    Compares bid vs ask orders and prevents them from matching.
    It drops ALL orders that would end up being matched.

    example:
        IOC BUY 100 at 1000
        POST_ONLY SELL 100 at 998
        POST_ONLY SELL 100 at 1000
        POST_ONLY SELL 100 at 1001
    -> cancels
        IOC BUY 100 at 1000
        POST_ONLY SELL 100 at 998
        POST_ONLY SELL 100 at 1000
    -> keeps
        POST_ONLY SELL 100 at 1001
    """

    def __init__(self) -> None:
        super().__init__()

    def process(
        self,
        context: mango.Context,
        model_state: ModelState,
        orders: typing.Sequence[mango.Order]
    ) -> typing.Sequence[mango.Order]:

        sell_prices = [order.price for order in orders if order.side == mango.Side.SELL]
        buy_prices = [order.price for order in orders if order.side == mango.Side.BUY]

        if not sell_prices or not buy_prices:
            return orders

        min_sell_price = min(sell_prices)
        max_buy_price = max(buy_prices)

        def is_matched(order: mango.Order) -> bool:
            if order.side == mango.Side.SELL:
                matched = max_buy_price >= order.price
                if matched:
                    self._logger.info('Found self-matched order', extra=dict(self_matched_order=order))
                return matched
            matched = min_sell_price <= order.price
            if matched:
                self._logger.info('Found self-matched order', extra=dict(self_matched_order=order))
            return matched

        return [order for order in orders if not is_matched(order)]

    def __str__(self) -> str:
        return self.__class__.__name__


class SimpleTakerElement(Element):
    """
    Creates taker (IOC) BUY (SELL) orders in case the FP is above (below) best ask (bid)
    by some margin defined by cfg.taker_min_profitability.

    Executed quantity is min from proportion of best ask (bid) defined
    by cfg.taker_quantity_proportion or max allowed trade defined by current position and leverage
    model_state.values.best_quantity_buy (model_state.values.best_quantity_sell).
    """

    def __init__(
            self,
            cfg: MarketMakerConfiguration,
            is_perp: bool
    ):

        """
        :param is_perp: If True placed orders are not added to available inventory.
        """

        super().__init__()

        self.taker_quantity_proportion = cfg.taker_quantity_proportion
        self.taker_min_profitability = cfg.taker_min_profitability
        self.min_quote_size = cfg.min_quote_size

        self.is_perp = is_perp
        self.order_type = mango.OrderType.IOC

    def process(
            self,
            context: mango.Context,
            model_state: ModelState,
            orders: typing.Sequence[mango.Order]
    ) -> typing.Sequence[mango.Order]:

        new_orders: typing.Sequence[mango.Order] = []

        best_bid = model_state.top_bid
        best_ask = model_state.top_ask
        fair_price = model_state.values.fair_price

        if fair_price > best_ask.price * (Decimal(1) + self.taker_min_profitability):
            # We cannot send quantity higher than is allowed by our leverage and position
            quantity = min(
                best_ask.quantity * self.taker_quantity_proportion,
                model_state.values.best_quantity_buy
            )
            if quantity >= self.min_quote_size:
                new_orders.append(
                    mango.Order.from_basic_info(
                        mango.Side.BUY,
                        price=best_ask.price,
                        quantity=quantity,
                        order_type=self.order_type
                    )
                )
                self._logger.info(
                    'Initial (before reconciler) creating of IOC order',
                    extra=dict(
                        order=new_orders[-1],
                        best_quantity_buy=model_state.values.best_quantity_buy,
                        best_ask_quantity=best_ask.quantity,
                        taker_quantity_proportion=self.taker_quantity_proportion,
                        is_quantiy=quantity >= self.min_quote_size
                    )
                )

        if fair_price < best_bid.price * (Decimal(1) - self.taker_min_profitability):
            quantity = min(
                best_bid.quantity * self.taker_quantity_proportion,
                model_state.values.best_quantity_sell
            )
            if quantity >= self.min_quote_size:
                new_orders.append(
                    mango.Order.from_basic_info(
                        mango.Side.SELL,
                        price=best_bid.price,
                        quantity=quantity,
                        order_type=self.order_type
                    )
                )
                self._logger.info(
                    'Initial (before reconciler) creating of IOC order',
                    extra=dict(
                        order=new_orders[-1],
                        best_quantity_sell=model_state.values.best_quantity_sell,
                        best_bid_quantity=best_bid.quantity,
                        taker_quantity_proportion=self.taker_quantity_proportion,
                        is_quantiy=quantity >= self.min_quote_size
                    )
                )

        return new_orders

    def __str__(self) -> str:
        return self.__class__.__name__
