import logging
import typing
import time

import mango
from ..modelstate import ModelState
from mango.types_ import MarketMakerConfiguration


def _is_in_book(order: mango.Order, book_side: typing.Sequence[mango.Order]) -> bool:
    """Tests if the order is in book."""
    first_outside_price = None
    if order.side == mango.Side.BUY:
        # we are on bid, the book_side is decreasing in price
        for book_order in book_side:
            if order.client_id == book_order.client_id:
                return True
            if book_order.price < order.price:
                if first_outside_price is None:
                    first_outside_price = book_order.price
                if book_order.price < first_outside_price:
                    return False
    elif order.side == mango.Side.SELL:
        # we are on ask, the book_side is increasing in price
        for book_order in book_side:
            if order.client_id == book_order.client_id:
                return True
            if book_order.price > order.price:
                if first_outside_price is None:
                    first_outside_price = book_order.price
                if book_order.price > first_outside_price:
                    return False
    return False


def find_order_by_id(
    client_id: int,
    orders: typing.Sequence[mango.Order]
) -> typing.Optional[mango.Order]:
    """Finds order by id in orders, else returns None"""
    for order in orders:
        if order.client_id == client_id:
            return order
    return None


# # 🥭 OrderTrackerCancelAll class
#

class OrderTrackerCancelAll:

    """
    OrderTrackerCancellAll is an order-inflight management.

    It remembers all orders that we have send to the market
    even though they are not visible in the book yet.

    Flow:
    1) start
        - everything is empty
    2) order flow
        there are few possible order flow scenarios
        - to_be_in_book -> in_book -> to_be_canceled_from_book
            -> order is assumed to be actually canceled
        - to_be_in_book -> to_be_canceled -> order is assumed to be actually canceled

    WE ASSUME WE ARE MONITORING LIMIT/POST_ONLY AND SIMILAR MAKER ORDERS.

    WE ARE ASSUMING THAT CANCELS ARE CANCEL ALL ORDERS!!!

    Order states
        orders_to_be_in_book
        - orders were send to be created
        - we need timestamp when we have send the transaction that creates the order

        orders_in_book
        - orders were observed in book and were not yet canceled
        - we need timestamp when we have send the transaction that creates the order
          since the time we observe it is moved

        orders_to_be_canceled

        orders_to_be_canceled_from_book

    This is assuming we can update everything and that there is no updating
    based on age since last cancel all. This implies that we have all orders
    that could be in the market.
    """

    def __init__(self, cfg: MarketMakerConfiguration) -> None:
        self._logger: logging.Logger = logging.getLogger(self.__class__.__name__)

        # Orders that are in process of being written into the book.
        self.orders_to_be_in_book: typing.List[mango.Order] = []
        # Orders that are in the book.
        self.orders_in_book: typing.List[mango.Order] = []
        # Orders that are in process of being canceled.
        self.orders_to_be_canceled: typing.List[mango.Order] = []
        # Orders that are in process of being canceled and have been seen in book previously.
        self.orders_to_be_canceled_from_book: typing.List[mango.Order] = []

        # List of timestamps in which cancel all have been send together with create orders.
        self.cancel_all_timestamps: typing.List[float] = []

        # {client-id: timestamp}
        self._from_time: typing.Dict[int, float] = {}

        # Currently has no effect.
        self.threshold_life_in_flight: int = cfg.threshold_life_in_flight

    @property
    def all_orders(self) -> typing.List[mango.Order]:
        self._logger.debug(
            'Existing orders are: in_book: %s, to_be_in_book: %s, to_be_canceled: %s, to_be_canceled_from_book: %s',
            self.orders_in_book,
            self.orders_to_be_in_book,
            self.orders_to_be_canceled,
            self.orders_to_be_canceled_from_book
        )
        return [
            *self.orders_in_book,
            *self.orders_to_be_in_book,
            *self.orders_to_be_canceled,
            *self.orders_to_be_canceled_from_book
        ]

    def append_to_orders_to_be_in_book(self, order: mango.Order, timestamp: float) -> None:
        self.orders_to_be_in_book.append(order)
        self._from_time[order.client_id] = timestamp

    def append_to_orders_in_book(self, order: mango.Order) -> None:
        self.orders_in_book.append(order)

    def append_to_orders_to_be_canceled(self, order: mango.Order) -> None:
        self.orders_to_be_canceled.append(order)

    def append_to_orders_to_be_canceled_from_book(self, order: mango.Order) -> None:
        self.orders_to_be_canceled_from_book.append(order)

    def remove_from_orders_to_be_in_book(self, order: mango.Order) -> None:
        if order in self.orders_to_be_in_book:
            self.orders_to_be_in_book.remove(order)

    def remove_from_orders_in_book(self, order: mango.Order) -> None:
        if order in self.orders_in_book:
            self.orders_in_book.remove(order)

    def remove_from_orders_to_be_canceled_from_book(self, order: mango.Order) -> None:
        if order in self.orders_to_be_canceled_from_book:
            self.orders_to_be_canceled_from_book.remove(order)
        self._from_time = {
            order_client_id: t
            for order_client_id, t in self._from_time.items()
            if order_client_id != order.client_id
        }

    def remove_from_orders_to_be_canceled(
        self,
        order: mango.Order,
        keep_from_time: bool = False
    ) -> None:
        if order in self.orders_to_be_canceled:
            self.orders_to_be_canceled.remove(order)
        if not keep_from_time:
            self._from_time = {
                order_client_id: t
                for order_client_id, t in self._from_time.items()
                if order_client_id != order.client_id
            }

    def update_on_existing_orders(self, existing_orders: typing.List[mango.Order]) -> None:
        """
        Information received here is redundant.
        Method is kept for compatibility with code that might use other order trackers.

        The logic that might be here is actually contained within the self.update_on_orderbook.
        """
        pass

    def update_on_orderbook(self, model_state: ModelState) -> None:
        """
        This method updates the current state of the orders based new orderbook.

        1)
        Move orders that are in book from state orders_to_be_in_book to orders_in_book.
            If any order is moved, this gives us latest timestamp of valid information
                -> we can drop from "in flight" state older orders than those are being observed
                   in book.
            What might also happen, is that before the above observation happens
                we moved the order to orders_to_be_canceled.
                    ->  move order from orders_to_be_canceled to orders_to_be_canceled_from_book

        2)
        Orders that have been previously seen in orderbook and have been canceled
        are dropped from all states. In case they are not in orderbook.

        !!!WARNING!!! State two also includes trades - we have observed order in book,
            canceled it, order was filled, then we saw it disappear from book ->
            -> we are not able to guarantee that the order was canceled

        3)
        Drop all orders that are older than those in 1). But only in case that the order
        was created with cancel all!

        If the orderbook is empty, it does not mean that orders have been succesfully canceled
        or created.
        """
        bids = model_state.bids
        asks = model_state.asks

        moved_orders: typing.List[mango.Order] = []

        # 1) move orders from self.orders_to_be_in_book into self.orders_in_book
        # in case they are in the book
        for create_order in list(self.orders_to_be_in_book):
            book_side = bids if create_order.side == mango.Side.BUY else asks
            is_in_book = _is_in_book(create_order, book_side)
            self._logger.info(f'Moving from to_be_in_book to in_book: {is_in_book}{create_order}')
            if is_in_book:
                self.remove_from_orders_to_be_in_book(create_order)
                self.append_to_orders_in_book(create_order)
                moved_orders.append(create_order)
        # and the same for the other case
        for create_order in list(self.orders_to_be_canceled):
            book_side = bids if create_order.side == mango.Side.BUY else asks
            is_in_book = _is_in_book(create_order, book_side)
            self._logger.info(
                f'Moving from orders_to_be_canceled to orders_to_be_canceled_from_book:'
                f' {is_in_book}{create_order}'
            )
            if is_in_book:
                self.remove_from_orders_to_be_canceled(create_order, keep_from_time=True)
                self.append_to_orders_to_be_canceled_from_book(create_order)
                moved_orders.append(create_order)

        # 2)
        # Drop all orders from self.orders_to_be_canceled_from_book that
        # are not visible in orderbook.
        for cancel_order in list(self.orders_to_be_canceled_from_book):
            book_side = bids if cancel_order.side == mango.Side.BUY else asks
            if not _is_in_book(cancel_order, book_side):
                self.remove_from_orders_to_be_canceled_from_book(cancel_order)
                self.remove_from_orders_in_book(cancel_order)

        # 3)
        self._update_on_latest_cancel_all(moved_orders)

    def update_on_reconcile(
        self,
        to_place: typing.Optional[typing.List[mango.Order]] = None,
        to_cancel: typing.Optional[typing.List[mango.Order]] = None,
        timestamp: float = time.time()
    ) -> None:
        """
        This method updates the current state of the orders based on reconciled orders.
        """
        to_place = to_place if to_place is not None else []
        to_place = [order for order in to_place if order.order_type != mango.OrderType.IOC]
        to_cancel = to_cancel if to_cancel is not None else []

        # 2)
        # In case there were any cancels, there was cancel all -> remember it
        if to_cancel:
            self.cancel_all_timestamps.append(timestamp)

        # 3)
        # Since we are assuming that there has been cancel all in case there is any cancel
        # we want to move all orders to orders_to_be_canceled and orders_to_be_canceled_from_book.
        if to_cancel:
            for order in list(self.orders_to_be_in_book):
                self.remove_from_orders_to_be_in_book(order)
                self.append_to_orders_to_be_canceled(order)
            for order in list(self.orders_in_book):
                self.remove_from_orders_in_book(order)
                self.append_to_orders_to_be_canceled_from_book(order)

        # 1) order is important!!!
        # Update self.orders_to_be_in_book by the reconciled.to_place
        for order in to_place:
            self.append_to_orders_to_be_in_book(order, timestamp)

    def _update_on_latest_cancel_all(self, moved_orders: typing.List[mango.Order]) -> None:
        """
        The moved_orders are currently the only real prove that order went through.
        We need the most current moved order and based on that we update the state
        by dropping all orders (from all possible states) that were send to the market
        before the most current cancel that happened before the moved order.
        """
        self._logger.info(
            f'Updating latest cancel all based on count(moved_orders): {moved_orders}'
        )
        order_times: typing.List[float] = []
        for moved_order in moved_orders:
            order_time = [
                t
                for order_client_id, t in self._from_time.items()
                if order_client_id == moved_order.client_id
            ]
            self._logger.debug(f'Timestamps of {moved_order} is {order_time}')
            if order_time:
                order_times.append(order_time[0])
            if len(order_time) > 1:
                self._logger.info(
                    f'Found order that has more timestamp of creation. {moved_order}, {order_time}'
                )

        # confirmed cancels
        cancel_timestamps = [
            timestamp
            for timestamp in self.cancel_all_timestamps
            if timestamp in order_times
        ]
        # latest confirmed cancel
        latest_cancel_all = 0 if not cancel_timestamps else max(cancel_timestamps)

        self._logger.info(
            f'Removing orders based on timestamps: {latest_cancel_all}, {moved_orders}'
        )

        # Cancel everything prior to latest_cancel_all
        for order_client_id, t in list(self._from_time.items()):
            if t < latest_cancel_all:
                orders = [
                    *[
                        order
                        for order in self.orders_to_be_in_book if order.client_id == order_client_id
                    ],
                    *[order for order in self.orders_in_book if order.client_id == order_client_id],
                    *[
                        order
                        for order in self.orders_to_be_canceled if order.client_id == order_client_id
                    ],
                    *[
                        order
                        for order in self.orders_to_be_canceled_from_book
                        if order.client_id == order_client_id
                    ]
                ]
                order = None if not orders else orders[0]

                self._logger.info(f'Forgetting {order_client_id}, {order}')

                if order is not None:
                    self.remove_from_orders_to_be_in_book(order)
                    self.remove_from_orders_in_book(order)
                    self.remove_from_orders_to_be_canceled_from_book(order)
                    self.remove_from_orders_to_be_canceled(order)

    def __str__(self) -> str:
        return f'''OrderTracker [
    orders_in_book: {self.orders_in_book},
    orders_to_be_in_book: {self.orders_to_be_in_book}
    orders_to_be_canceled: {self.orders_to_be_canceled}
    orders_to_be_canceled_from_book: {self.orders_to_be_canceled_from_book}
    cancel_all_timestamps: {self.cancel_all_timestamps}
    _from_time: {self._from_time}
    threshold_life_in_flight: {self.threshold_life_in_flight}
]'''
