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


import typing
import time

from decimal import Decimal

import mango
from ..modelstate import ModelState
from .orderreconciler import OrderReconciler
from .reconciledorders import ReconciledOrders


# # 🥭 ToleranceOrderReconciler class
#
# Has a level of 'tolerance' around whether a desired order matches an existing order.
#
# There are two tolerance levels:
# * A tolerance for price matching
# * A tolderance for quantity matching
#
# Tolerances are expressed as a ratio. To match the existing value must be within +/- the tolderance
# of the desired value.
#
# Note:
# * A BUY only matches with a BUY, a SELL only matches with a SELL.
# * ID and Client ID are ignored when matching.
# * ModelState is ignored when matching.
#
class ToleranceOrderReconciler(OrderReconciler):
    def __init__(self, price_tolerance: Decimal, quantity_tolerance: Decimal, ioc_order_wait_seconds: Decimal = Decimal(0)) -> None:
        super().__init__()
        self.price_tolerance: Decimal = price_tolerance
        self.quantity_tolerance: Decimal = quantity_tolerance
        self.ioc_order_wait_seconds: Decimal = ioc_order_wait_seconds

        # These are initialized with time already so that we can mitigate potential errors/bugs
        # with model initialization with market data.
        self.latest_taker_order_timestamps: typing.Dict[mango.Side, float] = {
            mango.Side.BUY: time.time(),
            mango.Side.SELL: time.time()
        }

    @staticmethod
    def zero_tolerance_order_reconciler() -> "ToleranceOrderReconciler":
        return ToleranceOrderReconciler(Decimal(0), Decimal(0))

    def reconcile(self, _: ModelState, existing_orders: typing.Sequence[mango.Order], desired_orders: typing.Sequence[mango.Order]) -> ReconciledOrders:
        remaining_existing_orders: typing.List[mango.Order] = list(existing_orders)
        outcomes: ReconciledOrders = ReconciledOrders()
        for desired in desired_orders:
            if desired.order_type == mango.OrderType.IOC:
                # No need to look for acceptable order in case of IOC.
                latest_timestamp = self.latest_taker_order_timestamps[desired.side]
                current_timestamp = time.time()
                if current_timestamp - latest_timestamp > self.ioc_order_wait_seconds:
                    outcomes.to_place.append(desired)
                    self.latest_taker_order_timestamps[desired.side] = current_timestamp

            acceptable = self.find_acceptable_order(desired, remaining_existing_orders)
            if acceptable is None:
                outcomes.to_place += [desired]
            else:
                outcomes.to_keep += [acceptable]
                outcomes.to_ignore += [desired]
                remaining_existing_orders.remove(acceptable)

        # By this point we have removed all acceptable existing orders, so those that remain
        # should be cancelled.
        outcomes.to_cancel = remaining_existing_orders

        in_count = len(existing_orders) + len(desired_orders)
        out_count = len(outcomes.to_place) + len(outcomes.to_cancel) + len(outcomes.to_keep) + len(outcomes.to_ignore)
        if in_count != out_count:
            raise Exception(
                f"Failure processing all desired orders. Count of orders in: {in_count}. Count of orders out: {out_count}.")

        return outcomes

    def find_acceptable_order(self, desired: mango.Order, existing_orders: typing.Sequence[mango.Order]) -> typing.Optional[mango.Order]:
        for existing in existing_orders:
            if self.is_within_tolderance(existing, desired):
                return existing
        return None

    def is_within_tolderance(self, existing: mango.Order, desired: mango.Order) -> bool:
        if existing.side != desired.side:
            return False

        price_tolerance: Decimal = existing.price * self.price_tolerance
        if desired.price > (existing.price + price_tolerance):
            return False

        if desired.price < (existing.price - price_tolerance):
            return False

        quantity_tolerance: Decimal = existing.quantity * self.quantity_tolerance
        if desired.quantity > (existing.quantity + quantity_tolerance):
            return False

        if desired.quantity < (existing.quantity - quantity_tolerance):
            return False

        return True

    def __str__(self) -> str:
        return f"« ToleranceOrderReconciler [price tolerance: {self.price_tolerance}, quantity tolerance: {self.quantity_tolerance}] »"
