from decimal import Decimal

from mango.marketmaking.ordertracker import OrderTracker
from mango.types_ import MarketMakerConfiguration
from ..fakes import fake_model_state
from mango.lotsizeconverter import NullLotSizeConverter
import mango
from mango.constants import SYSTEM_PROGRAM_ADDRESS


def test_order_tracker() -> None:
    cfg = MarketMakerConfiguration(
        pair='fake/fake',
        oracle_providers=['fake'],
        min_quote_size=Decimal(0),
        spread_ratio=Decimal(0),
        position_size_ratios=[Decimal('0.4'), Decimal('0.4')],
        existing_order_tolerance=Decimal(0),
        confidence_interval_level=[Decimal(0)],
        leverage=Decimal(0),
        existing_order_price_tolerance=Decimal('0.001'),
    )
    model_state = fake_model_state(
        orderbook=mango.OrderBook(
            "FAKE",
            NullLotSizeConverter(),
            [mango.Order(price=Decimal('1'), quantity=Decimal(1), id=0, client_id=0, side=mango.Side.BUY, order_type=mango.OrderType.LIMIT, owner=SYSTEM_PROGRAM_ADDRESS)],
            [mango.Order(price=Decimal('2'), quantity=Decimal(1), id=0, client_id=0, side=mango.Side.SELL, order_type=mango.OrderType.LIMIT, owner=SYSTEM_PROGRAM_ADDRESS)],
        )
    )

    tracker = OrderTracker(cfg)

    assert not tracker.all_orders
    assert not tracker._from_time['orders_to_be_in_book']
    assert not tracker._from_time['orders_to_be_canceled']

    # send create order
    order_1 = mango.Order(price=Decimal('0.9'), quantity=Decimal(1), id=1, client_id=1, side=mango.Side.BUY, order_type=mango.OrderType.LIMIT, owner=SYSTEM_PROGRAM_ADDRESS)
    tracker.update_on_reconcile(to_place=[order_1])

    assert not tracker.orders_in_book
    assert not tracker.orders_to_be_canceled
    assert tracker.orders_to_be_in_book == [order_1]
    assert len(tracker._from_time['orders_to_be_in_book']) == 1
    assert not tracker._from_time['orders_to_be_canceled']

    # the order is still not in the book
    tracker.update_on_orderbook(model_state)

    assert not tracker.orders_in_book
    assert not tracker.orders_to_be_canceled
    assert tracker.orders_to_be_in_book == [order_1]
    assert len(tracker._from_time['orders_to_be_in_book']) == 1
    assert not tracker._from_time['orders_to_be_canceled']

    # send another two orders (and remember first one)
    order_2 = mango.Order(price=Decimal('1.9'), quantity=Decimal(1), id=2, client_id=2, side=mango.Side.SELL, order_type=mango.OrderType.LIMIT, owner=SYSTEM_PROGRAM_ADDRESS)
    order_3 = mango.Order(price=Decimal('2.0'), quantity=Decimal(1), id=3, client_id=3, side=mango.Side.SELL, order_type=mango.OrderType.LIMIT, owner=SYSTEM_PROGRAM_ADDRESS)
    tracker.update_on_reconcile(to_place=[order_2, order_3])

    assert not tracker.orders_in_book
    assert not tracker.orders_to_be_canceled

    assert tracker.orders_to_be_in_book == [order_1, order_2, order_3]
    assert len(tracker._from_time['orders_to_be_in_book']) == 3
    assert not tracker._from_time['orders_to_be_canceled']

    # order 2 appears in the book on existing orders
    tracker.update_on_existing_orders([order_2])

    assert tracker.orders_in_book == [order_2]
    assert not tracker.orders_to_be_canceled
    assert tracker.orders_to_be_in_book == [order_1, order_3]
    assert len(tracker._from_time['orders_to_be_in_book']) == 2
    assert not tracker._from_time['orders_to_be_canceled']

    # order 1 appears in the book on orderbook
    model_state = fake_model_state(
        orderbook=mango.OrderBook(
            "FAKE",
            NullLotSizeConverter(),
            [
                order_1,
                mango.Order(price=Decimal('1'), quantity=Decimal(1), id=0, client_id=0, side=mango.Side.BUY, order_type=mango.OrderType.LIMIT, owner=SYSTEM_PROGRAM_ADDRESS)
            ],
            [
                order_2,
                mango.Order(price=Decimal('2'), quantity=Decimal(1), id=0, client_id=0, side=mango.Side.SELL, order_type=mango.OrderType.LIMIT, owner=SYSTEM_PROGRAM_ADDRESS)
            ],
        )
    )
    tracker.update_on_orderbook(model_state)

    assert tracker.orders_in_book == [order_2, order_1]
    assert not tracker.orders_to_be_canceled
    assert tracker.orders_to_be_in_book == [order_3]
    assert len(tracker._from_time['orders_to_be_in_book']) == 1
    assert not tracker._from_time['orders_to_be_canceled']

    assert tracker.get_side_orders_to_be_in_book(mango.Side.SELL) == [order_3]
    assert not tracker.get_side_orders_to_be_in_book(mango.Side.BUY)

    # cancel order_3 and order_1
    tracker.update_on_reconcile(to_cancel=[order_1, order_3])

    assert tracker.orders_in_book == [order_2]
    assert tracker.orders_to_be_canceled == [order_1, order_3]
    assert not tracker.orders_to_be_in_book
    assert not tracker._from_time['orders_to_be_in_book']
    assert len(tracker._from_time['orders_to_be_canceled']) == 2

    # update on previous book (should loose track of order_3)
    tracker.update_on_orderbook(model_state)

    assert tracker.orders_in_book == [order_2]
    assert tracker.orders_to_be_canceled == [order_1]
    assert not tracker.orders_to_be_in_book
    assert not tracker._from_time['orders_to_be_in_book']
    assert len(tracker._from_time['orders_to_be_canceled']) == 1

    # update on existing orders only with order_1 (order_2 was filled)
    tracker.update_on_existing_orders([order_1])

    assert not tracker.orders_in_book
    assert tracker.orders_to_be_canceled == [order_1]
    assert not tracker.orders_to_be_in_book
    assert not tracker._from_time['orders_to_be_in_book']
    assert len(tracker._from_time['orders_to_be_canceled']) == 1

    # update on book without order one
    model_state = fake_model_state(
        orderbook=mango.OrderBook(
            "FAKE",
            NullLotSizeConverter(),
            [mango.Order(price=Decimal('1'), quantity=Decimal(1), id=0, client_id=0, side=mango.Side.BUY, order_type=mango.OrderType.LIMIT, owner=SYSTEM_PROGRAM_ADDRESS)],
            [mango.Order(price=Decimal('2'), quantity=Decimal(1), id=0, client_id=0, side=mango.Side.SELL, order_type=mango.OrderType.LIMIT, owner=SYSTEM_PROGRAM_ADDRESS)],
        )
    )
    tracker.update_on_orderbook(model_state)

    assert not tracker.orders_in_book
    assert not tracker.orders_to_be_canceled
    assert not tracker.orders_to_be_in_book
    assert not tracker._from_time['orders_to_be_in_book']
    assert not tracker._from_time['orders_to_be_canceled']

    # order 3 cancel failed, but the create went through
    tracker.update_on_existing_orders([order_3])

    assert tracker.orders_in_book == [order_3]
    assert not tracker.orders_to_be_canceled
    assert not tracker.orders_to_be_in_book
    assert not tracker._from_time['orders_to_be_in_book']
    assert not tracker._from_time['orders_to_be_canceled']
