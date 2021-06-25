from typing import List
from decimal import Decimal

from ...context import mango
from ...fakes import fake_context, fake_model_state, fake_order

from mango.marketmaking.orderchain.chkpelements import PreventCrossingElement


def test_crossing() -> None:
    context = fake_context()
    model_state = fake_model_state()

    orders: List[mango.Order] = [
        fake_order(
            price=Decimal(1000),
            quantity=Decimal(100),
            side=mango.Side.BUY,
            order_type=mango.OrderType.IOC
        ),
        fake_order(
            price=Decimal(998),
            quantity=Decimal(100),
            side=mango.Side.SELL,
            order_type=mango.OrderType.POST_ONLY
        ),
        fake_order(
            price=Decimal(1000),
            quantity=Decimal(100),
            side=mango.Side.SELL,
            order_type=mango.OrderType.POST_ONLY
        ),
        fake_order(
            price=Decimal(1001),
            quantity=Decimal(100),
            side=mango.Side.SELL,
            order_type=mango.OrderType.POST_ONLY
        )
    ]

    result: PreventCrossingElement = PreventCrossingElement().process(context, model_state, orders)

    assert result == [orders[-1]], 'Only one order should be left after the self crossing check.'


def test_not_crossing() -> None:
    context = fake_context()
    model_state = fake_model_state()

    orders: List[mango.Order] = [
        fake_order(
            price=Decimal(1000),
            quantity=Decimal(100),
            side=mango.Side.BUY,
            order_type=mango.OrderType.IOC
        ),
        fake_order(
            price=Decimal(1001),
            quantity=Decimal(100),
            side=mango.Side.SELL,
            order_type=mango.OrderType.POST_ONLY
        )
    ]

    result: PreventCrossingElement = PreventCrossingElement().process(context, model_state, orders)

    assert result == orders, 'All orders should have been kept.'
