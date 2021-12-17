from decimal import Decimal
import math
import time

from unittest.mock import MagicMock

from mango.types_ import MarketMakerConfiguration
import mango.pricemodel.simplepricemodel
import mango
from ..fakes import fake_model_state, fake_price, fake_public_key


def test_fair_price_model_eval(monkeypatch) -> None:
    cfg = MarketMakerConfiguration(
        pair='fake/fake',
        oracle_providers=['fake'],
        price_center_volume=Decimal(1000),
        price_weights=[Decimal('0.5')],
        ewma_halflife=Decimal('100'),
        # These do not influence the result of the test
        min_quote_size=Decimal(0),
        spread_ratio=Decimal(0),
        position_size_ratios=[Decimal('0.4'), Decimal('0.4')],
        existing_order_tolerance=Decimal(0),
        confidence_interval_level=[Decimal(0)],
        leverage=Decimal(0),
        existing_order_price_tolerance=Decimal('0.001')
    )
    # Only "important" part in orderbook are prices in orders.
    orderbook = mango.OrderBook(
        symbol='fake/fake',
        lot_size_converter=mango.LotSizeConverter(
            base=mango.Instrument(symbol='fake', name='fake', decimals=Decimal(0)),
            base_lot_size=Decimal(0),
            quote=mango.Instrument(symbol='fake', name='fake', decimals=Decimal(0)),
            quote_lot_size=Decimal(0)
        ),
        bids=[mango.Order(
            id=0,
            client_id=0,
            owner=fake_public_key(),
            side=mango.Side.BUY,
            price=Decimal(99),
            quantity=Decimal(1),
            order_type=mango.OrderType.LIMIT,
        )],
        asks=[mango.Order(
            id=0,
            client_id=0,
            owner=fake_public_key(),
            side=mango.Side.SELL,
            price=Decimal(101),
            quantity=Decimal(1),
            order_type=mango.OrderType.LIMIT,
        )],
    )

    # since price_weights=0.5 -> book and price based on oracle ewma(price) are averaged
    # (very simply said)

    # book mid price (and also its ewma) is always 100 and the final fair price (FP)
    # should converge to this price
    # halflife is 100(seconds) and the updates timedelta too, this means that the next ewma(price)
    # is average between new update and older ewma

    # the oracle processed price (PA) is (in case of 1 oracle)
    # PA = OracleWeight * (Oracle - (EWMA(Oracle) - EWMA(BookMid))
    # In our case
    # PA = 0.5 * (Oracle - EWMA(Oracle) + 100)
    # The final FP
    # FP = PA + (1-sum(oracle weights)) * PC
    # FP = 0.5 * (Oracle - EWMA(Oracle) + 100) + 0.5 * 100
    # FP = 0.5 * Oracle - 0.5 * EWMA(Oracle) + 100
    # when all above aggregated, the step by step is
    # FP_0 = 0.5 * 100 - 0.5 * EWMA([100]) + 100 = 100
    # FP_1 = 0.5 * 102 - 0.5 * EWMA([102, 100]) + 100 = 0.5 * 102 - 0.5 * 101 + 100 = 100.5
    # FP_2 = 0.5 * 102 - 0.5 * EWMA([102, 102, 100]) + 100 = 0.5 * 102 - 0.5 * 101.5 + 100 = 100.25
    # FP_3 = 0.5 * 102 - 0.5 * EWMA([102, 102, 102, 100]) + 100 = 0.5 * 102 - 0.5 * 101.75 + 100
    #       = 100.125

    FP_model = mango.pricemodel.simplepricemodel.FairPriceModel(cfg)

    times = sorted([float(t) for t in range(10000, 11000, 100)] * 2)
    monkeypatch.setattr(time, "time", MagicMock(side_effect=times))

    oracle_prices = [100] + [102] * 9
    targets = [
        Decimal('100.0'),
        Decimal('100.50'),
        Decimal('100.250'),
        Decimal('100.1250'),
        Decimal('100.06250'),
        Decimal('100.031250'),
        Decimal('100.0156250'),
        Decimal('100.00781250'),
        Decimal('100.003906250'),
        Decimal('100.0019531250')
    ]

    for price, target in zip(oracle_prices, targets):
        model_state = fake_model_state(
            price=fake_price(price=Decimal(price)),
            orderbook=orderbook
        )
        fp_result = FP_model.eval(model_state).fair_price
        assert math.isclose(fp_result, target, rel_tol=0.000001)
