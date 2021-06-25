import math
from decimal import Decimal

from mango.types_ import MarketMakerConfiguration
from mango.marketmaking.bookmodel import BookModel
import mango
from ..fakes import fake_model_state, fake_public_key


def test_book_model_eval(monkeypatch) -> None:

    cfg = MarketMakerConfiguration(
        book_quote_cutoff=Decimal(5),
        price_center_volume=Decimal(6),
        pair='fake/fake',
        oracle_providers=['fake'],
        price_weights=[Decimal('0.5')],
        ewma_halflife=Decimal('100'),
        # These do not influence the result of the test
        min_quote_size=Decimal(0),
        spread_ratio=Decimal(0),
        position_size_ratios=[Decimal('0.4'), Decimal('0.4')],
        existing_order_tolerance=Decimal(0),
        confidence_interval_level=[Decimal(0)],
        leverage=Decimal(0),
        existing_order_price_tolerance=Decimal('0.001'),
    )

    # Only prices are important in the orderbook.
    orderbook = mango.OrderBook(
        symbol='fake/fake',
        lot_size_converter=mango.LotSizeConverter(
            base=mango.Instrument(symbol='fake', name='fake', decimals=Decimal(0)),
            base_lot_size=Decimal(0),
            quote=mango.Instrument(symbol='fake', name='fake', decimals=Decimal(0)),
            quote_lot_size=Decimal(0)
        ),
        bids=[
            mango.Order(
                id=0,
                client_id=0,
                owner=fake_public_key(),
                side=mango.Side.BUY,
                price=Decimal(100),
                quantity=Decimal(100),
                order_type=mango.OrderType.LIMIT,
            ),
            mango.Order(
                id=0,
                client_id=0,
                owner=fake_public_key(),
                side=mango.Side.BUY,
                price=Decimal(99),
                quantity=Decimal(1),
                order_type=mango.OrderType.LIMIT,
            ),
        ],
        asks=[
            mango.Order(
                id=0,
                client_id=0,
                owner=fake_public_key(),
                side=mango.Side.SELL,
                price=Decimal(101),
                quantity=Decimal(1),
                order_type=mango.OrderType.LIMIT,
            ),
            mango.Order(
                id=0,
                client_id=0,
                owner=fake_public_key(),
                side=mango.Side.SELL,
                price=Decimal(102),
                quantity=Decimal(5),
                order_type=mango.OrderType.LIMIT,
            ),
        ],
    )

    model = BookModel(cfg)
    model_state = fake_model_state(orderbook=orderbook)

    values = model.eval(model_state)

    price_center_target = Decimal('100.833333333333333333333333333333333')
    book_spread_target = Decimal('0.00991735537190082644628099173553719012')

    assert math.isclose(values.price_center, price_center_target, rel_tol=1e-12)
    assert math.isclose(values.book_spread, book_spread_target, rel_tol=1e-12)
