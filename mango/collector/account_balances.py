import logging
from typing import Sequence, Dict, Tuple

from functools import reduce
from argparse import ArgumentParser
from datetime import datetime as dt
from decimal import Decimal
from collections import defaultdict
from time import sleep

from sqlalchemy import create_engine
from sqlalchemy import Table, Column, DateTime, String, MetaData
import mango
from mango.configuration import load_configuration
from mango.types_ import Configuration
from mango.heartbeat import heartbeat, heartbeat_init
from mango.chkpcontextconf import ChkpContextConfiguration


SPL_TOKENS = mango.market.InventorySource.SPL_TOKENS
NAME = 'account_balances'

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.INFO)


def parse_args(args=None):

    parser = ArgumentParser(
        description='Periodically collects and record balances'
        ' of all group tokens, SPL toknes and SOL in wallet'
    )
    parser.add_argument('config', type=str, nargs=1, help='Which configuration to use')
    mango.ContextBuilder.add_command_line_parameters(parser)
    mango.Wallet.add_command_line_parameters(parser)

    return parser.parse_args(args)


def make_db_sink(cfg):

    engine = create_engine(cfg.dashboard_url)

    collection = MetaData()
    table = Table(
        f'{cfg.prefix}{cfg.instance_prefix}{NAME}',
        collection,
        Column('timestamp', DateTime),
        Column('address', String),
        Column('symbol', String),
        Column('value', String),
        Column('price', String),
    )
    table.create(engine, checkfirst=True)

    db = engine.connect()
    stmt = table.insert()

    def insert(record):
        return db.execute(stmt, record)

    return insert


def get_price(context: mango.Context, symbol, cfg: Configuration):

    if symbol == 'USDC':
        return Decimal(1)

    if symbol == 'Pure SOL':
        symbol = 'SOL'

    try:
        oracle_provider = mango.create_oracle_provider(context, 'pyth')
        market = context.market_lookup.find_by_symbol(f'{symbol}/USDC')
        oracle = oracle_provider.oracle_for_market(context, market)
        return oracle.fetch_price(context).mid_price

    except AttributeError:  # if the price cannot be fetched
        return None


def collect_orders(
        context: mango.Context,
        wallet: mango.Wallet,
        account: mango.Account,
        markets: Sequence[mango.Market]
) -> Dict[str, Decimal]:
    """Collects spot and serum orders.  Perp orders are excluded."""

    orders = defaultdict(Decimal)
    for market in markets:

        if isinstance(market, mango.PerpMarketStub):
            # PerpMarketStub because the market is not "ensure_loaded()".
            # Its not needed to load the market here.
            continue

        market_operations: mango.MarketOperations = \
            mango.create_market_operations(
                context,
                wallet,
                account,
                market,
            )

        open_orders = market_operations.load_my_orders()

        for order in open_orders:
            if order.side == mango.Side.SELL:
                orders[market.base.symbol] += order.quantity
            elif order.side == mango.Side.BUY:
                orders[market.quote.symbol] += order.quantity * order.price

    return orders


def collect_positions(
        cfg: Configuration,
        context: mango.Context,
        slots: Sequence[mango.AccountSlot]
) -> Tuple[Dict[str, Decimal], Dict[str, Decimal]]:
    """Collects perp positions."""

    prices = {}
    positions = defaultdict(Decimal)
    for slot in slots:
        if slot.perp_account is not None:

            symbol = slot.base_instrument.name
            price = get_price(context, symbol, cfg)
            position = slot.perp_account.base_token_value.value

            positions[symbol] += position
            positions[slot.quote_token_bank.token.name] -= position * price
            prices[symbol] = price

    return positions, prices


class PhonyWallet:

    def __init__(self, address: str):
        self.address = address

    @property
    def secret_key(self):
        raise NotImplementedError('PhonyWallet has no secret_key')


def override_args(cfg: Configuration, args):
    args.cluster_url = [mango.ClusterUrlData(cfg.solana.cluster_url)]
    args.stale_data_pause_before_retry = cfg.balance_collector.stale_data_pauses_before_retry


def main(args):

    cfg = load_configuration(args.config[0])
    heartbeat_init(cfg.paths.account_balances_heartbeat)
    override_args(cfg, args)
    context: mango.Context = mango.ContextBuilder.from_command_line_parameters(args)
    context.cfg = ChkpContextConfiguration(
        marinade_api_url=cfg.solana.marinade_api_url
    )
    LOGGER.info(f'Configuration loaded: {cfg}')
    address = cfg.solana.address
    sink = make_db_sink(cfg.database)
    group = mango.Group.load(context)
    wallet = PhonyWallet(address)
    markets = [
        context.market_lookup.find_by_symbol(pair)
        for pair in cfg.balance_collector.watch_markets
    ]
    LOGGER.info(f'Loading markets: {markets}')

    while True:

        now = dt.now()

        spl_markets = [
            market
            for market in markets
            if market.inventory_source == SPL_TOKENS
        ]

        orders = collect_orders(context, wallet, None, spl_markets)

        watch_symbols = set(cfg.balance_collector.watch_symbols)
        spl_symbols = reduce(
            set.union,
            (
                set([market.base.symbol, market.quote.symbol])
                for market in spl_markets
            ),
            watch_symbols
        )
        for symbol in spl_symbols:

            token = context.instrument_lookup.find_by_symbol(symbol)
            balance = mango.InstrumentValue.fetch_total_value(context, address, token)

            sink(dict(
                timestamp=now,
                address=address,
                symbol=symbol,
                price=get_price(context, symbol, cfg),
                value=balance.value + orders[symbol],
            ))

        heartbeat(cfg.paths.account_balances_heartbeat)

        sol_balance = context.client.get_balance(address)
        sink(dict(
            timestamp=now,
            address=address,
            symbol='Pure SOL',
            price=get_price(context, 'SOL', cfg),
            value=sol_balance,
        ))

        heartbeat(cfg.paths.account_balances_heartbeat)

        mango_accounts = mango.Account.load_all_for_owner(context, address, group)
        mango_symbols = reduce(
            set.union,
            (
                set([market.base.symbol, market.quote.symbol])
                for market in markets
            ),
            set()
        )
        for account in mango_accounts:
            orders = collect_orders(context, wallet, account, markets)
            slots = [
                slot
                for slot in account.slots_by_index
                if slot is not None and slot.base_instrument.name in mango_symbols
            ]
            positions, prices = collect_positions(cfg, context, slots)

            for slot in slots:
                if slot is not None:
                    symbol = slot.base_instrument.name
                    price = prices.get(symbol) or get_price(context, symbol, cfg)
                    sink(dict(
                        timestamp=now,
                        address=str(account.address),
                        symbol=symbol,
                        price=price,
                        value=slot.net_value.value + orders[symbol] + positions[symbol],
                    ))

        heartbeat(cfg.paths.account_balances_heartbeat)
        sleep(cfg.collection_interval_seconds)


if __name__ == '__main__':

    args = parse_args()
    main(args)
