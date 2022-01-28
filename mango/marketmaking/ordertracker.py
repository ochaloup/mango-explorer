import logging
import typing
import time

import mango
from ..modelstate import ModelState
from mango.types_ import MarketMakerConfiguration


def _is_in_book(order: mango.Order, book_side: typing.Sequence[mango.Order]) -> bool:
    """Tests if the order is in book."""
    if order.side == mango.Side.BUY:
        # we are on bid, the book_side is decreasing in price
        for book_order in book_side:
            if order.client_id == book_order.client_id:
                return True
            if book_order.price < order.price:
                return False
    elif order.side == mango.Side.SELL:
        # we are on ask, the book_side is increasing in price
        for book_order in book_side:
            if order.client_id == book_order.client_id:
                return True
            if book_order.price > order.price:
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


# # 🥭 OrderTracker class
#
# FIXME: add description
# FIXME: how does it work with order fills?

class OrderTracker:

    """
    OrderTracker is an order-inflight management.

    It remembers all orders that we have send to the market
    even though they are not visible in the book yet.

    AT THIS MOMENT WE ARE NOT CANCELING ORDERS THAT ARE NOT YET IN THE BOOK!!!

    Flow:
    1) start
        - everything is empty
    2) we want to create order
        - if new order is not similar is appended into orders_to_be_in_book

    WE ASSUME WE ARE MONITORING LIMIT/POST_ONLY AND SIMILAR MAKER ORDERS.
    """

    def __init__(self, cfg: MarketMakerConfiguration) -> None:
        self._logger: logging.Logger = logging.getLogger(self.__class__.__name__)

        # Orders that are in the book.
        self.orders_in_book: typing.List[mango.Order] = []
        # Orders that are in process of being written into the book.
        self.orders_to_be_in_book: typing.List[mango.Order] = []
        # Orders that are in process of being canceled.
        self.orders_to_be_canceled: typing.List[mango.Order] = []

        self._from_time: typing.Dict[str, typing.List[typing.Tuple[float, mango.Order]]] = {
            'orders_to_be_in_book': [],
            'orders_to_be_canceled': []
        }

        self.threshold_life_in_flight: int = cfg.threshold_life_in_flight

    @property
    def all_orders(self) -> typing.List[mango.Order]:
        self._logger.info(
            'Existing orders are: in_book: %s, to_be_in_book: %s, to_be_canceled: %s',
            self.orders_in_book,
            self.orders_to_be_in_book,
            self.orders_to_be_canceled
        )
        return [
            *self.orders_in_book,
            *self.orders_to_be_in_book,
            *self.orders_to_be_canceled
        ]

    def get_side_orders_to_be_in_book(self, side: mango.Side) -> typing.List[mango.Order]:
        side_orders = [
            order
            for order in self.orders_to_be_in_book
            if order.side == side
        ]
        self._logger.info('To be order found on %s are: %s', side, side_orders)
        return side_orders

    def append_to_orders_to_be_in_book(self, order: mango.Order) -> None:
        self.orders_to_be_in_book.append(order)
        self._from_time['orders_to_be_in_book'].append((time.time(), order))

    def append_to_orders_to_be_canceled(self, order: mango.Order) -> None:
        self.orders_to_be_canceled.append(order)
        self._from_time['orders_to_be_canceled'].append((time.time(), order))

    def remove_from_orders_to_be_in_book(self, order: mango.Order) -> None:
        self.orders_to_be_in_book.remove(order)
        self._from_time['orders_to_be_in_book'] = [
            (t, order_)
            for t, order_ in self._from_time['orders_to_be_in_book']
            if order_ != order
        ]

    def remove_from_orders_to_be_canceled(self, order: mango.Order) -> None:
        self.orders_to_be_canceled.remove(order)
        self._from_time['orders_to_be_canceled'] = [
            (t, order_)
            for t, order_ in self._from_time['orders_to_be_canceled']
            if order_ != order
        ]

    def _update_on_time(self) -> None:
        """
        Updates the internal state by dropping orders that are too old to be in
        self.orders_to_be_in_book or self.orders_to_be_canceled.
        """
        # Check by time, that the orders being canceled and orders being created
        # are not in the corresponding lists for too long.
        time_ = time.time()

        for t, order in self._from_time['orders_to_be_in_book']:
            if time_ >= t + self.threshold_life_in_flight:
                self.remove_from_orders_to_be_in_book(order)

        for t, order in self._from_time['orders_to_be_canceled']:
            if time_ >= t + self.threshold_life_in_flight:
                self.remove_from_orders_to_be_canceled(order)

    def update_on_existing_orders(self, existing_orders: typing.List[mango.Order]) -> None:
        """
        Sometimes there might be order that gets slipped.
        For example order that we cancel before we notice it in the book.
        And if this cancel fails, the order will appear in the book.
        """
        # Adding slipped order as per description
        for order in existing_orders:
            if find_order_by_id(order.client_id, self.orders_in_book) is None:
                # the order is not in orders_in_book, but it can be in to_be_canceled
                # if find_order_by_id(order.client_id, self.orders_to_be_canceled) is None:
                #     pass
                to_be_order = find_order_by_id(order.client_id, self.orders_to_be_in_book)
                if to_be_order is not None:
                    self.remove_from_orders_to_be_in_book(to_be_order)
                    self.orders_in_book.append(order)
                elif find_order_by_id(order.client_id, self.orders_to_be_canceled) is None \
                        and find_order_by_id(order.client_id, self.orders_in_book) is None:
                    # not in self.orders_to_be_in_book, self.orders_to_be_canceled
                    # and not in self.orders_in_book
                    self.orders_in_book.append(order)

        # Dealing with filled and/or canceled orders
        for order in list(self.orders_in_book):
            if find_order_by_id(order.client_id, existing_orders) is None:
                self.orders_in_book.remove(order)
        for order in list(self.orders_to_be_canceled):
            if find_order_by_id(order.client_id, existing_orders) is None:
                self.remove_from_orders_to_be_canceled(order)

        self._update_on_time()

    def update_on_orderbook(self, model_state: ModelState) -> None:
        """
        This method updates the current state of the orders based new orderbook.
        """
        bids = model_state.bids
        asks = model_state.asks

        # 1)
        # if self.orders_to_be_canceled are not in the book
        # -> drop them from self.orders_to_be_canceled
        for cancel_order in list(self.orders_to_be_canceled):
            book_side = bids if cancel_order.side == mango.Side.BUY else asks
            if not _is_in_book(cancel_order, book_side):
                self.remove_from_orders_to_be_canceled(cancel_order)

        # 2)
        # move orders from self.orders_to_be_in_book into self.orders_in_book
        # in case they are in the book
        for create_order in list(self.orders_to_be_in_book):
            book_side = bids if create_order.side == mango.Side.BUY else asks
            if _is_in_book(create_order, book_side):
                self.remove_from_orders_to_be_in_book(create_order)
                self.orders_in_book.append(create_order)

        self._update_on_time()

    def update_on_reconcile(
        self,
        to_place: typing.Optional[typing.List[mango.Order]] = None,
        to_cancel: typing.Optional[typing.List[mango.Order]] = None,
        timestamp: int = None
    ) -> None:
        """
        This method updates the current state of the orders based on reconciled orders.
        """
        to_place = to_place if to_place is not None else []
        to_cancel = to_cancel if to_cancel is not None else []

        # 1)
        # Update self.orders_to_be_in_book by the reconciled.to_place
        for order in to_place:
            self.append_to_orders_to_be_in_book(order)

        # 2)
        # Update self.orders_to_be_canceled by the reconciled.to_cancel
        for cancel_order in to_cancel:
            found_order = find_order_by_id(cancel_order.client_id, self.orders_in_book)
            if found_order is not None:
                self.orders_in_book.remove(found_order)
                self.append_to_orders_to_be_canceled(found_order)
            found_order = find_order_by_id(cancel_order.client_id, self.orders_to_be_in_book)
            if found_order is not None:
                self.remove_from_orders_to_be_in_book(found_order)
                self.append_to_orders_to_be_canceled(found_order)

        self._update_on_time()

    def __str__(self) -> str:
        return f'''OrderTracker [
    orders_in_book: {self.orders_in_book},
    orders_to_be_in_book: {self.orders_to_be_in_book}
    orders_to_be_canceled: {self.orders_to_be_canceled}
    _from_time: {self._from_time}
    threshold_life_in_flight: {self.threshold_life_in_flight}
]'''
