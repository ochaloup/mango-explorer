from typing import Sequence, List

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

SPL_TOKENS = mango.market.InventorySource.SPL_TOKENS
NAME = 'account_balances'


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


def get_price(context, symbol, cfg: Configuration):

    if symbol == 'USDC':
        return Decimal(1)

    if symbol == 'Pure SOL':
        symbol = 'SOL'

    try:
        oracle_provider = mango.create_oracle_provider(context, 'pyth', cfg)
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
) -> List[Decimal]:
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


class PhonyWallet:

    def __init__(self, address: str):
        self.address = address

    @property
    def secret_key(self):
        raise NotImplementedError('PhonyWallet has no secret_key')


def main(args):

    cfg = load_configuration(args.config[0])
    heartbeat_init(cfg.paths.account_balances_heartbeat)
    args.cluster_url = 'http://falk2.chkp.io'
    context = mango.ContextBuilder.from_command_line_parameters(args)
    address = cfg.account.address
    sink = make_db_sink(cfg.database)
    group = mango.Group.load(context)
    wallet = PhonyWallet(address)

    markets = [
        context.market_lookup.find_by_symbol(pair)
        for pair in cfg.account.watch_markets
    ]

    while True:

        now = dt.now()

        spl_markets = [
            market
            for market in markets
            if market.inventory_source == SPL_TOKENS
        ]

        orders = collect_orders(context, wallet, None, spl_markets)

        spl_symbols = reduce(
            set.union,
            (
                set([market.base.symbol, market.quote.symbol])
                for market in spl_markets
            ),
            set(cfg.account.watch_symbols)
        )
        for symbol in spl_symbols:

            token = context.token_lookup.find_by_symbol(symbol)
            balance = mango.TokenValue.fetch_total_value(context, address, token)

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
        for account in mango_accounts:
            orders = collect_orders(context, wallet, account, markets)
            for asset in account.basket_tokens:
                if asset is not None:
                    symbol = asset.token_info.token.name
                    sink(dict(
                        timestamp=now,
                        address=str(account.address),
                        symbol=symbol,
                        price=get_price(context, symbol, cfg),
                        value=asset.net_value.value + orders[symbol],
                    ))

        heartbeat(cfg.paths.account_balances_heartbeat)
        sleep(20)


if __name__ == '__main__':

    args = parse_args()
    main(args)
