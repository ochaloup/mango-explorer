from decimal import Decimal
import math

from mango.marketmaking.ordertrackercancelall import OrderTrackerCancelAll
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
        threshold_life_in_flight=15
    )
    model_state = fake_model_state(
        orderbook=mango.OrderBook(
            "FAKE",
            NullLotSizeConverter(),
            [mango.Order(price=Decimal('1'), quantity=Decimal(1), id=0, client_id=0, side=mango.Side.BUY, order_type=mango.OrderType.LIMIT, owner=SYSTEM_PROGRAM_ADDRESS)],
            [mango.Order(price=Decimal('2'), quantity=Decimal(1), id=0, client_id=0, side=mango.Side.SELL, order_type=mango.OrderType.LIMIT, owner=SYSTEM_PROGRAM_ADDRESS)],
        )
    )

    tracker = OrderTrackerCancelAll(cfg)

    assert not tracker.all_orders
    assert not tracker._from_time
    assert not tracker._from_time_longterm
    assert tracker.delay_metric.latest is None

    # send create order
    order_1 = mango.Order(price=Decimal('0.9'), quantity=Decimal(1), id=1, client_id=1, side=mango.Side.BUY, order_type=mango.OrderType.LIMIT, owner=SYSTEM_PROGRAM_ADDRESS)
    tracker.update_on_reconcile(to_place=[order_1], timestamp=100.)

    assert not tracker.orders_in_book
    assert not tracker.orders_to_be_canceled
    assert tracker.orders_to_be_in_book == [order_1]
    assert not tracker.orders_to_be_canceled_from_book
    assert len(tracker._from_time) == 1
    assert len(tracker._from_time_longterm) == 1
    assert tracker.delay_metric.latest is None

    # the order is still not in the book
    tracker.update_on_orderbook(model_state)

    assert not tracker.orders_in_book
    assert not tracker.orders_to_be_canceled
    assert tracker.orders_to_be_in_book == [order_1]
    assert not tracker.orders_to_be_canceled_from_book
    assert len(tracker._from_time) == 1
    assert len(tracker._from_time_longterm) == 1
    assert tracker.delay_metric.latest is None

    # send another two orders and cancel first one
    order_2 = mango.Order(price=Decimal('1.9'), quantity=Decimal(1), id=2, client_id=2, side=mango.Side.BUY, order_type=mango.OrderType.LIMIT, owner=SYSTEM_PROGRAM_ADDRESS)
    order_3 = mango.Order(price=Decimal('2.0'), quantity=Decimal(1), id=3, client_id=3, side=mango.Side.SELL, order_type=mango.OrderType.LIMIT, owner=SYSTEM_PROGRAM_ADDRESS)
    tracker.update_on_reconcile(to_place=[order_2, order_3], to_cancel=[order_1], timestamp=110.)

    assert not tracker.orders_in_book
    assert tracker.orders_to_be_canceled == [order_1]
    assert tracker.orders_to_be_in_book == [order_2, order_3]
    assert not tracker.orders_to_be_canceled_from_book
    assert len(tracker._from_time) == 3
    assert len(tracker._from_time_longterm) == 3
    assert tracker.delay_metric.latest is None

    # update_on_existing_orders does nothing
    tracker.update_on_existing_orders([order_2], timestamp=110.5)

    assert not tracker.orders_in_book
    assert tracker.orders_to_be_canceled == [order_1]
    assert tracker.orders_to_be_in_book == [order_2, order_3]
    assert not tracker.orders_to_be_canceled_from_book
    assert len(tracker._from_time) == 3
    assert len(tracker._from_time_longterm) == 2
    assert math.isclose(tracker.delay_metric.latest, 0.5, abs_tol=0.01)

    # order 2 and 3 appears in the book on existing orders
    # order 1, since orders 2 and 3 were send with cancel
    # and the transaction went through
    model_state = fake_model_state(
        orderbook=mango.OrderBook(
            "FAKE",
            NullLotSizeConverter(),
            [
                order_2,
                mango.Order(price=Decimal('1'), quantity=Decimal(1), id=0, client_id=0, side=mango.Side.BUY, order_type=mango.OrderType.LIMIT, owner=SYSTEM_PROGRAM_ADDRESS)
            ],
            [
                order_3,
                mango.Order(price=Decimal('2'), quantity=Decimal(1), id=0, client_id=0, side=mango.Side.SELL, order_type=mango.OrderType.LIMIT, owner=SYSTEM_PROGRAM_ADDRESS)
            ],
        )
    )
    tracker.update_on_orderbook(model_state)

    assert tracker.orders_in_book == [order_2, order_3]
    assert not tracker.orders_to_be_canceled
    assert not tracker.orders_to_be_in_book
    assert not tracker.orders_to_be_canceled_from_book
    assert len(tracker._from_time) == 2
    assert len(tracker._from_time_longterm) == 2
    assert math.isclose(tracker.delay_metric.latest, 0.5, abs_tol=0.01)

    # reconcile with nothing
    tracker.update_on_reconcile(timestamp=111.)

    assert tracker.orders_in_book == [order_2, order_3]
    assert not tracker.orders_to_be_canceled
    assert not tracker.orders_to_be_in_book
    assert not tracker.orders_to_be_canceled_from_book
    assert len(tracker._from_time) == 2
    assert len(tracker._from_time_longterm) == 2
    assert math.isclose(tracker.delay_metric.latest, 0.5, abs_tol=0.01)

    # cancel orders, create new ones
    order_4 = mango.Order(price=Decimal('1.9'), quantity=Decimal(1), id=4, client_id=4, side=mango.Side.BUY, order_type=mango.OrderType.LIMIT, owner=SYSTEM_PROGRAM_ADDRESS)
    order_5 = mango.Order(price=Decimal('2.0'), quantity=Decimal(1), id=5, client_id=5, side=mango.Side.SELL, order_type=mango.OrderType.LIMIT, owner=SYSTEM_PROGRAM_ADDRESS)
    tracker.update_on_reconcile(to_place=[order_4, order_5], to_cancel=[order_2, order_3], timestamp=130.)

    assert not tracker.orders_in_book
    assert not tracker.orders_to_be_canceled
    assert tracker.orders_to_be_in_book == [order_4, order_5]
    assert tracker.orders_to_be_canceled_from_book == [order_2, order_3]
    assert len(tracker._from_time) == 4
    assert len(tracker._from_time_longterm) == 4
    assert math.isclose(tracker.delay_metric.latest, 0.5, abs_tol=0.01)

    # show order_4 and 5 in book with delay so that orders 2 and 3 disapper from tracker
    model_state = fake_model_state(
        orderbook=mango.OrderBook(
            "FAKE",
            NullLotSizeConverter(),
            [order_4],
            [order_5],
        )
    )

    tracker.update_on_orderbook(model_state)
    assert tracker.orders_in_book == [order_4, order_5]
    assert not tracker.orders_to_be_canceled
    assert not tracker.orders_to_be_in_book
    assert not tracker.orders_to_be_canceled_from_book
    assert len(tracker._from_time) == 2
    assert len(tracker._from_time_longterm) == 4
    assert math.isclose(tracker.delay_metric.latest, 0.5, abs_tol=0.01)
