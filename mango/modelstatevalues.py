from decimal import Decimal
from typing import Optional, Sequence

from mango.orders import Order
from dataclasses import dataclass


@dataclass
class ModelStateValues:

    existing_orders: Optional[Sequence[Order]] = None

    position_base: Optional[Decimal] = None
    position_quote: Optional[Decimal] = None
    total_available: Optional[Decimal] = None
    leveraged_available: Optional[Decimal] = None

    price_center: Optional[Decimal] = None
    book_spread: Optional[Decimal] = None

    fair_price: Optional[Decimal] = None
    fair_spread: Optional[Decimal] = None

    best_quote_price_bid: Optional[Decimal] = None
    best_quote_price_ask: Optional[Decimal] = None

    hedge_price_bias_bid: Optional[Decimal] = None
    hedge_price_bias_ask: Optional[Decimal] = None

    best_quantity_buy: Optional[Decimal] = None
    best_quantity_sell: Optional[Decimal] = None

    def update(self, values: "ModelStateValues") -> None:
        valid = {k: v for k, v in values.__dict__.items() if v is not None}
        self.__dict__.update(valid)
