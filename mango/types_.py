from decimal import Decimal
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field

from mango import Side


class ConfigurationError(Exception):
    pass


def wrap_decimal(num, name):
    if isinstance(num, Decimal):
        return num
    if isinstance(num, str) or isinstance(num, int):
        return Decimal(num)
    raise ConfigurationError(
        f'Bad value for {name}: {type(num)}.  Only int, str and Decimal are allowed.')


@dataclass
class PathsConfiguration:
    tmpdir: str
    datadir: str
    orca_arbitrage_heartbeat: Optional[str] = None
    saber_arbitrage_heartbeat: Optional[str] = None
    trader_heartbeat_dir: Optional[str] = None
    account_balances_heartbeat: Optional[str] = None
    price_collector_heartbeat: Optional[str] = None


@dataclass
class DatabaseConfiguration:
    prefix: str
    instance_prefix: str
    dashboard_url: str


@dataclass
class AccountConfiguration:
    cluster_url: str
    marinade_api_url: str
    address: str
    key_file: str
    orca_proxy_url: Optional[str] = None
    cluster_url_wss: Optional[str] = None
    watch_markets: List[str] = field(default_factory=list)
    watch_symbols: List[str] = field(default_factory=list)


@dataclass
class MarketMakerConfiguration:

    """
    :param spread_ratio: Half of the ratio of prices we quote at.
    :param position_size_ratios: Order scaling parameter.
    :param leverage: Maximal leverage at which we enter the market.
    :param min_quote_sise: Minimum size we quote in the market.
    :param price_weights: Determines weights for linear combination
        of prices from oracles; the rest to one is given to price from book.
    """

    pair: str
    oracle_providers: List[str]
    min_quote_size: Decimal
    spread_ratio: Decimal
    position_size_ratios: List[Decimal]
    existing_order_tolerance: Decimal
    confidence_interval_level: List[Decimal]
    leverage: Decimal
    spread_narrowing_coef: Decimal = 0
    price_center_volume: Decimal = 1000
    existing_order_price_tolerance: Decimal = None
    existing_order_quantity_tolerance: Decimal = None
    price_weights: List[Decimal] = field(default_factory=list)
    poll_interval_seconds: int = 10
    min_price_increment_ratio: Decimal = "0.00005"

    def __post_init__(self):
        self.min_quote_size = wrap_decimal(self.min_quote_size, 'min_quote_size')
        self.spread_ratio = wrap_decimal(self.spread_ratio, 'spread_ratio')
        self.position_size_ratios = list(map(
            lambda x: wrap_decimal(x, 'position_size_ratios'),
            self.position_size_ratios
        ))
        self.existing_order_tolerance = wrap_decimal(
            self.existing_order_tolerance,
            'existing_order_tolerance'
        )
        self.existing_order_price_tolerance = wrap_decimal(
            self.existing_order_price_tolerance
            or self.existing_order_tolerance,
            'existing_order_price_tolerance'
        )
        self.existing_order_quanity_tolerance = wrap_decimal(
            self.existing_order_quantity_tolerance
            or self.existing_order_tolerance,
            'existing_order_quantity_tolerance'
        )

        self.confidence_interval_level = list(map(
            lambda x: wrap_decimal(x, 'confidence_interval_level'),
            self.confidence_interval_level
        ))
        self.leverage = wrap_decimal(self.leverage, 'leverage')
        self.price_center_volume = wrap_decimal(self.price_center_volume, 'price_center_volume')

        self.price_weights = list(map(
            lambda x: wrap_decimal(x, 'price_weights'),
            self.price_weights
        ))

        self.spread_narrowing_coef = wrap_decimal(
            self.spread_narrowing_coef,
            'spread_narrowing_coef'
        )

        for i, weight in enumerate(self.price_weights):
            if not 0 <= weight <= 1:
                raise ConfigurationError(f'price_weights[{i}] is outside [0, 1]')

        self.min_price_increment_ratio = wrap_decimal(
            self.min_price_increment_ratio,
            'min_price_increment_ratio'
        )

        if 2 * self.min_price_increment_ratio > self.existing_order_price_tolerance:
            raise ConfigurationError('2 * min_price_increment_ratio > existing_order_price_tolerance')  # noqa: E501


@dataclass
class PriceCollectorConfiguration:
    server_name: str
    symbols: Tuple[str, List[str]]
    pause_duration: int
    max_number_of_observations: int


@dataclass
class SimpleArbitrageConfiguration:
    delay_after_arbitrage_seconds: int
    market_symbol: str
    oracle_provider_name: str
    position_size_ratios: Dict[Side, Decimal]
    min_trade_size: Decimal
    profitability_scaling_size: Decimal
    profitable_relative_deviation: Decimal
    # the threshold_relative_quantity is basically a slippage parametr
    threshold_relative_quantity: Decimal
    poll_interval_seconds: int
    orca_symbol: Optional[str] = None
    saber_symbol: Optional[str] = None

    def __post_init__(self):
        # We initially have bad types:
        # noinspection PyTypeChecker
        self.position_size_ratios = {
            Side.BUY: wrap_decimal(self.position_size_ratios[0], 'position_size_ratios[BUY]'),
            Side.SELL: wrap_decimal(self.position_size_ratios[1], 'position_size_ratios[SELL]')
        }
        self.min_trade_size = wrap_decimal(
            self.min_trade_size, 'min_trade_size'
        )
        self.profitability_scaling_size = wrap_decimal(
            self.profitability_scaling_size, 'profitability_scaling_size'
        )
        self.profitable_relative_deviation = wrap_decimal(
            self.profitable_relative_deviation, 'profitable_relative_deviation'
        )
        self.threshold_relative_quantity = wrap_decimal(
            self.threshold_relative_quantity, 'threshold_relative_quantity'
        )

        if self.orca_symbol is None and self.saber_symbol is None:
            raise ValueError('At least one of the orca_symbol or saber_symbol has to be non-None.')


@dataclass
class FillCollectorConfiguration:
    server_name: str
    symbols: Tuple[str, List[str]]
    max_number_of_observations: int
    message_types: List[str]


@dataclass
class MarinadeStakingConfiguration:
    config_path: str
    poll_interval_seconds: int
    min_staking_quantity: Decimal
    keep_amount_sol: Decimal
    delay_after_staking_seconds: int
    wsol_address: str
    staking_on: bool

    def __post_init__(self):
        self.min_staking_quantity = wrap_decimal(
            self.min_staking_quantity,
            'min_staking_quantity'
        )
        self.keep_amount_sol = wrap_decimal(
            self.keep_amount_sol,
            'keep_amount_sol'
        )
        self.staking_on = self.staking_on == 'True'


@dataclass
class Configuration:
    account: AccountConfiguration
    paths: PathsConfiguration
    database: DatabaseConfiguration
    marketmaker: MarketMakerConfiguration
    price_collector: Optional[PriceCollectorConfiguration]
    fill_collector: Optional[FillCollectorConfiguration]
    simplearbitrage: Optional[Dict[str, SimpleArbitrageConfiguration]]
    saber_arbitrage: Optional[Dict[str, SimpleArbitrageConfiguration]]
    marinade_staking: Optional[MarinadeStakingConfiguration]
