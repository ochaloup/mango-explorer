# # ⚠ Warning
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT
# LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN
# NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#
# [🥭 Mango Markets](https://mango.markets/) support is available at:
#   [Docs](https://docs.mango.markets/)
#   [Discord](https://discord.gg/67jySBhxrg)
#   [Twitter](https://twitter.com/mangomarkets)
#   [Github](https://github.com/blockworks-foundation)
#   [Email](mailto:hello@blockworks.foundation)


import abc
import argparse
import logging
import mango
import typing

from ...modelstate import ModelState

from decimal import Decimal
from mango.types_ import Configuration


# # 🥭 Element class
#
# A base class for a part of a chain that can take in a sequence of elements and process them, changing
# them as desired.
#
# Only `Order`s returned from `process()` method are passed to the next element of the chain.
#
class Element(metaclass=abc.ABCMeta):
    def __init__(self) -> None:
        self._logger: logging.Logger = logging.getLogger(self.__class__.__name__)

    @staticmethod
    def add_command_line_parameters(parser: argparse.ArgumentParser) -> None:
        pass

    @staticmethod
    def from_command_line_parameters(args: argparse.Namespace) -> "Element":
        raise NotImplementedError("Element.from_command_line_parameters() is not implemented on the base type.")

    @abc.abstractmethod
    def process(self, context: mango.Context, model_state: ModelState, orders: typing.Sequence[mango.Order]) -> typing.Sequence[mango.Order]:
        raise NotImplementedError("Element.process() is not implemented on the base type.")

    def __repr__(self) -> str:
        return f"{self}"

    def __str__(self) -> str:
        return """« Element »"""


# CHKP addition
def compute_pcd(limit, model_state):

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


class LeveragedFixedRatiosElement(Element):
    """
    Quotes

       position_size_ratio ((leverage - 1) bankroll + position)

    position can be negative
    bankroll is the sum of positions, i.e. how much funds do we have on the account
    position_size_ratio can be different for bid and ask
    index 0 is for bid, index 1 for ask
    """

    def __init__(
            self,
            cfg: Configuration,
            is_perp: bool,
            order_type: mango.OrderType = mango.OrderType.POST_ONLY,
    ):

        """
        :param is_perp: If True placed orders are not added to available inventory.
        """

        super().__init__()

        self.spread_ratio = cfg.spread_ratio
        self.position_size_ratios = cfg.position_size_ratios
        self.leverage = cfg.leverage
        self.min_quote_size = cfg.min_quote_size
        self.price_weights = {
            name: weight
            for name, weight
            in zip(cfg.oracle_providers, cfg.price_weights)
        }
        self.price_center_volume = cfg.price_center_volume

        self.is_perp = is_perp
        self.order_type = order_type

    def process(
            self,
            context: mango.Context,
            model_state: ModelState,
            existing_orders: typing.Sequence[mango.Order],
            orders: typing.Sequence[mango.Order],
    ) -> typing.Sequence[mango.Order]:

        new_orders: typing.Sequence[mango.Order] = []

        buy_quantity = model_state.values.best_quantity_buy
        bid = model_state.values.best_quote_price_bid
        if buy_quantity >= self.min_quote_size:
            new_orders.append(
                mango.Order.from_basic_info(
                    mango.Side.BUY,
                    price=bid,
                    quantity=buy_quantity,
                    order_type=self.order_type
                )
            )

        sell_quantity = model_state.values.best_quantity_sell
        ask = model_state.values.best_quote_price_ask
        if sell_quantity >= self.min_quote_size:
            new_orders.append(
                mango.Order.from_basic_info(
                    mango.Side.SELL,
                    price=ask,
                    quantity=sell_quantity,
                    order_type=self.order_type
                )
            )

        return new_orders

    def __str__(self) -> str:
        return f"{self.__class__.__name__}(spread={self.spread_ratios}, position_size_ratios={self.position_size_ratios}, leverage={self.leverage}, order_type={self.order_type}"


class LimitSpreadNarrowingElement(Element):

    """
    May modifiy an `Order`s price if it would result in quoting inside spread.
    Quoting inside spread is more risky, so do it more gradualy.

      PKB' = PB + spread_narrowing_coef (PKB - PB),

    where PKB' is the price of the new quote inside spread, PB is best BID and
    PKB is the original suggested price for the quote.  Mirror for ASK.
    """

    def __init__(self, cfg: Configuration):
        super().__init__()
        self.cfg = cfg

    def process(
            self,
            context: mango.Context,
            model_state: ModelState,
            existing_orders: typing.Sequence[mango.Order],
            orders: typing.Sequence[mango.Order]
    ) -> typing.Sequence[mango.Order]:

        coef = self.cfg.spread_narrowing_coef
        min_ratio = self.cfg.min_price_increment_ratio

        new_orders: typing.List[mango.Order] = []
        for order in orders:

            top_bid: typing.Optional[mango.Order] = model_state.top_bid
            top_ask: typing.Optional[mango.Order] = model_state.top_ask

            if (
                    order.side == mango.Side.BUY
                    and top_bid is not None
                    and top_ask is not None
                    and order.price >= top_bid.price
            ):

                price_increment = max(
                    coef * (order.price - top_bid.price),
                    min_ratio * top_bid.price
                )
                new_buy_price: Decimal = top_bid.price + price_increment
                new_buy: mango.Order = order.with_price(new_buy_price)
                self.logger.debug(
                    f"""Order change - would tighten spread {top_bid.price if top_bid else None} / {top_ask.price}:
                Old: {order}
                New: {new_buy}""")
                new_orders.append(new_buy)

            elif (
                    order.side == mango.Side.SELL
                    and top_bid is not None
                    and top_ask is not None
                    and order.price <= top_ask.price
            ):
                price_increment = max(
                    coef * (top_ask.price - order.price),
                    min_ratio * top_ask.price
                )
                new_sell_price: Decimal = top_ask.price - price_increment
                new_sell: mango.Order = order.with_price(new_sell_price)
                self.logger.debug(
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
