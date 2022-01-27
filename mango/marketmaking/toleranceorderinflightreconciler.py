import typing
import time

import mango
from ..modelstate import ModelState
from .reconciledorders import ReconciledOrders
from .toleranceorderreconciler import ToleranceOrderReconciler


# # 🥭 ToleranceOrderInFlightReconciler class
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
# Differes from ToleranceOrderReconciler by taking into account inflight orders
# and by either canceling all orders and creating new ones or doing nothing.
#
class ToleranceOrderInFlightReconciler(ToleranceOrderReconciler):
    """
    This is a special purpose class, that will be replaced/deleted in a moment
    when we have orderbooks on time.

    This class assumes that we do not know what we have in book, we only know
    what might be in the book. (Everything we have send in the last few moments)

    When any order that might be in book deviates from desired orders we want to cancel all
    and create all new.
    """

    def is_within_tolderance_to_all(
        self,
        remaining_existing_orders: typing.Sequence[mango.Order],
        desired: mango.Order,
    ) -> bool:
        remaining_side = [
            order
            for order in remaining_existing_orders
            if order.side == desired.side
        ]
        for remaining in remaining_side:
            if not self.is_within_tolderance(self, remaining, desired):
                return False
        return True

    def is_empty_side_and_full_book(
        self,
        remaining_existing_orders: typing.Sequence[mango.Order],
        desired_nonIOC: typing.Sequence[mango.Order],
    ) -> bool:
        """
        True if there are no desired_nonIOC and some remaining_existing_orders for any side.
        """
        for side in [mango.OrderType.BUY, mango.OrderType.SELL]:
            remaining_side = [
                order
                for order in remaining_existing_orders
                if order.side == side
            ]
            desired_side = [
                order
                for order in desired_nonIOC
                if order.side == side
            ]
            if remaining_side and not desired_side:
                return True
        return False

    def is_side_empty(
        self,
        remaining_existing_orders: typing.Sequence[mango.Order],
        desired: mango.Order,
    ) -> bool:
        return not [
            order
            for order in remaining_existing_orders
            if order.order_type == desired.order_type
        ]

    def cancel_all_instructions(
        self,
        remaining_existing_orders: typing.Sequence[mango.Order],
        desired_orders: typing.Sequence[mango.Order],
    ) -> ReconciledOrders:
        outcomes: ReconciledOrders = ReconciledOrders()
        outcomes.to_keep = []
        outcomes.to_cancel = remaining_existing_orders
        outcomes.to_place = desired_orders
        return outcomes

    def reconcile(
        self,
        _: ModelState,
        existing_orders: typing.Sequence[mango.Order],
        desired_orders: typing.Sequence[mango.Order]
    ) -> ReconciledOrders:
        """

        :param existing_orders: all orders that might be in the market
        """
        remaining_existing_orders: typing.List[mango.Order] = list(existing_orders)
        outcomes: ReconciledOrders = ReconciledOrders()

        desired_IOC = [
            order
            for order in desired_orders
            if order.order_type == mango.OrderType.IOC
        ]
        desired_nonIOC = [
            order
            for order in desired_orders
            if order.order_type != mango.OrderType.IOC
        ]

        # First deal with IOC orders
        for desired in desired_IOC:
            if desired.order_type == mango.OrderType.IOC:
                # No need to look for acceptable order in case of IOC.
                latest_timestamp = self.latest_taker_order_timestamps[desired.side]
                current_timestamp = time.time()
                if current_timestamp - latest_timestamp > self.ioc_order_wait_seconds:
                    outcomes.to_place.append(desired)
                    self.latest_taker_order_timestamps[desired.side] = current_timestamp
        to_place_ioc = [
            order for order in outcomes.to_place if order.order_type == mango.OrderType.IOC
        ]

        # if we do not want to have order on given side and we have some on book
        # -> cancel all and create all new (IOC based on the above)
        if self.is_empty_side_and_full_book(desired_nonIOC, remaining_existing_orders):
            return self.cancel_all_instructions(
                remaining_existing_orders,
                desired_nonIOC + to_place_ioc
            )

        # Now we know that there is no strict cancel/create because of not wanting order in book
        # If any desired_nonIOC deviates enough from any remaining_existing_orders on given side
        # -> cancel all
        for desired in desired_nonIOC:
            if self.is_within_tolderance_to_all(remaining_existing_orders, desired):
                # desired does not deviate from any order on given book side
                # this means we do not need to cancel all (yet)
                # we want to create the order in case the given side is empty
                if self.is_side_empty(remaining_existing_orders, desired):
                    outcomes.to_place += [desired]
            else:
                # cancel everything - the desired order deviates from at least one order
                # that could potentially be on its side
                return self.cancel_all_instructions(
                    remaining_existing_orders,
                    desired_nonIOC + to_place_ioc
                )

        # At this point we do not want to cancel anything, we might have some orders to place
        # The existing_orders are to be kept (we are not canceling anything)
        # and the desired_orders that are not "to_place" are being ignored
        outcomes.to_keep += existing_orders
        outcomes.to_ignore += [order for order in desired_orders if order not in outcomes.to_place]

        # Validate that the orders that came in are equivalent to orders coming out.
        in_count = len(existing_orders) + len(desired_orders)
        out_count = len(outcomes.to_place) + len(outcomes.to_cancel) + len(outcomes.to_keep) + len(outcomes.to_ignore)
        if in_count != out_count:
            raise Exception(
                f"Failure processing all desired orders. Count of orders in: {in_count}. Count of orders out: {out_count}.")

        return outcomes

    def __str__(self) -> str:
        return f"ToleranceOrderInFlightReconciler [price tolerance: {self.price_tolerance}, quantity tolerance: {self.quantity_tolerance}]"
