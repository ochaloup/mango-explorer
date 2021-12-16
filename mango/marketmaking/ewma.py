from typing import Optional
from decimal import Decimal
import math
import time


class EWMA:
    """
    Calculates latest value x(t) as
    x(t) = alpha * current_value + (1-alpha) * x(t-1)
    where alpha = 1 - e ^ (-ln2 / halflife * delta_t)
    """

    def __init__(self, halflife: Decimal = Decimal('0')) -> None:
        if halflife < 0:
            raise ValueError(f'halflife should be >= 0, but is {halflife}')
        self.halflife = halflife
        self.latest: Optional[Decimal] = None

        self._latest_timestamp: Optional[float] = None

    def update(self, value: Decimal) -> None:
        if self.latest is None:
            self.latest = value
            self._latest_timestamp = time.time()
        else:
            if self.halflife == Decimal('0'):
                self.latest = value
            else:
                _newest_timestamp = time.time()
                t_delta = _newest_timestamp - self._latest_timestamp
                alpha = Decimal(1 - math.exp(- math.log(2) / float(self.halflife) * t_delta))
                self.latest = alpha * value + (1 - alpha) * self.latest
                self._latest_timestamp = _newest_timestamp
