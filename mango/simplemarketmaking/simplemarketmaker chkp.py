import logging
import time
import traceback
import typing
from typing import List
from math import floor

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import mango
from mango.client import TransactionException
from mango.orders import OrderBook
from mango.types_ import Configuration, MarketMakerConfiguration

# # 🥭 SimpleMarketMaker class
#
# This is a simple demonstration of market making. It is intended to show how to do some things
# market makers require. It is not intended to be an actual, useful market maker.
#
# This market maker performs the following steps:
#
# 1. Cancel any orders
# 2. Update current state
#   2a. Fetch current prices
#   2b. Fetch current inventory
# 3. Figure out what orders to place
# 4. Place those orders
# 5. Sleep for a defined period
# 6. Repeat from Step 1
#
# There are many features missing that you'd expect in a more realistic market maker.
# Here are just a few:
# * There is very little error handling
# * There is no retrying of failed actions
# * There is no introspection on whether orders are filled
# * There is no inventory management, nor any attempt to balance number of filled buys
#   with number of filled sells.
# * Token prices and quantities are rounded to the token mint's decimals, not the market's
#   tick size and lot size
# * The strategy of placing orders at a fixed spread around the mid price without taking
#   any other factors into account is likely to be costly
# * Place and Cancel instructions aren't batched into single transactions
#


def floor_quote(ratio, x, tol):
    """Increase ratio until there is something to quote."""

    size = ratio * x
    if size < tol:

        if x < tol or ratio < 1e-18:
            return 0

        return tol

    return floor(size / tol) * tol


class SimpleModelState:
    orderbook: mango.Watcher[OrderBook]
    oracle_price: mango.Watcher[Decimal]


class SimpleSerumModelState(SimpleModelState):

    # inspired by marketstatebuilderfactory._websocket_model_state_builder_factory()

    def __init__(
            self,
            cfg: Configuration,
            context: mango.Context,
            disposer: mango.DisposePropagator,
            websocket_manager: mango.WebSocketSubscriptionManager,
            health_check: mango.HealthCheck,
            market: mango.Market,
    ):

        super().__init__()

        market = mango.ensure_market_loaded(context, market)

        self.oracle_price = mango.build_price_watcher(
            cfg,
            context,
            websocket_manager,
            health_check,
            disposer,
            cfg.marketmaker.oracle_providers[0],
            market,
        )

        if isinstance(market, mango.SerumMarket):
            self.orderbook: mango.Watcher[mango.OrderBook] = \
                mango.build_orderbook_watcher(
                    context,
                    websocket_manager,
                    health_check,
                    market.underlying_serum_market
            )


class SimpleMarketMaker:

    def __init__(
            self,
            cfg: MarketMakerConfiguration,
            context: mango.Context,
            wallet: mango.Wallet,
            market: mango.Market,
            market_operations: mango.MarketOperations,
            oracle: mango.Oracle,
            spread_ratio: Decimal,
            position_size_ratios: List[Decimal],
            existing_order_tolerance: Decimal,
            pause: timedelta,
            model: SimpleModelState,
    ):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.context: mango.Context = context
        self.cfg: MarketMakerConfiguration = cfg
        self.wallet: mango.Wallet = wallet
        self.market: mango.Market = market
        self.market_operations: mango.MarketOperations = market_operations
        self.oracle: mango.Oracle = oracle
        self.spread_ratio: Decimal = spread_ratio
        self.position_size_ratios: List[Decimal] = position_size_ratios
        self.existing_order_tolerance: Decimal = existing_order_tolerance
        self.pause: timedelta = pause
        self.model = model
        self.stop_requested = False
        self.health_filename = "/var/tmp/mango_healthcheck_simple_market_maker"

        self.logger.info("Configuration: %s", cfg)

    def start(self):

        while not self.stop_requested:
            self.logger.info("\nStarting fresh iteration.")

            time_start = time.time()

            try:
                # Update current state
                inventory = self.fetch_inventory()
                self.logger.info(f"Current inventory is {inventory}")

                current_orders = self.market_operations.load_my_orders()

                # Calculate what we want the orders to be.
                bid_price, ask_price = self.calculate_order_prices()
                buy_quantity, sell_quantity = self.calculate_order_quantities(
                    inventory, current_orders
                )

                buy_orders = [order for order in current_orders if order.side == mango.Side.BUY]
                if self.orders_require_action(buy_orders, bid_price, buy_quantity):
                    self.logger.info("Cancelling BUY orders.")
                    for order in buy_orders:
                        self.market_operations.cancel_order(order)
                    if not buy_orders:
                        try:
                            self.market_operations.settle()
                            self.logger.info('Settled BUY market operations.')
                        except TransactionException:  # no orders to settle
                            pass
                    buy_order: mango.Order = mango.Order.from_basic_info(
                        mango.Side.BUY, bid_price, buy_quantity, mango.OrderType.POST_ONLY)
                    if buy_quantity > Decimal('0'):
                        self.market_operations.place_order(buy_order)
                    else:
                        self.logger.info(
                            'Not quoting BUY since quantity is %s (price: %s)',
                            buy_quantity,
                            bid_price
                        )
                else:
                    self.logger.info(
                        'Doing nothing with BUY orders. bid_price: %s, buy_quantity: %s',
                        bid_price,
                        buy_quantity
                    )

                sell_orders = [order for order in current_orders if order.side == mango.Side.SELL]
                if self.orders_require_action(sell_orders, ask_price, sell_quantity):
                    self.logger.info("Cancelling SELL orders.")
                    for order in sell_orders:
                        self.market_operations.cancel_order(order)
                    if not sell_orders:
                        try:
                            self.market_operations.settle()
                            self.logger.info('Settled SELL market operations.')
                        except TransactionException:  # no orders to settle
                            pass
                    sell_order: mango.Order = mango.Order.from_basic_info(
                        mango.Side.SELL, ask_price, sell_quantity, mango.OrderType.POST_ONLY)
                    if sell_quantity > Decimal('0'):
                        self.market_operations.place_order(sell_order)
                    else:
                        self.logger.info(
                            'Not quoting SELL since quantity is %s (price: %s)',
                            sell_quantity,
                            ask_price
                        )
                else:
                    self.logger.info(
                        'Doing nothing with SELL orders. ask_price: %s, sell_quantity: %s',
                        ask_price,
                        sell_quantity
                    )

                self.update_health_on_successful_iteration()

            except Exception as exception:
                self.logger.warning(
                    f'Pausing and continuing after problem running market-making iteration:'
                    f' {exception} - {traceback.format_exc()}'
                )

            # Wait and hope for fills.
            time_sleep = max(0, self.pause.seconds - (time.time() - time_start))
            self.logger.info(f'Pausing for {time_sleep} seconds.')
            time.sleep(time_sleep)

        self.logger.info('Stopped.')

        self.close()

    def stop(self):
        self.logger.info("Stop requested.")
        self.stop_requested = True
        Path(self.health_filename).unlink(missing_ok=True)

    def close(self):
        self.logger.info("Cleaning up.")
        orders = self.market_operations.load_my_orders()
        for order in orders:
            self.market_operations.cancel_order(order)

    def fetch_inventory(self) -> typing.Sequence[typing.Optional[mango.InstrumentValue]]:
        if self.market.inventory_source == mango.InventorySource.SPL_TOKENS:
            base_account = mango.TokenAccount.fetch_largest_for_owner_and_token(
                self.context, self.wallet.address, self.market.base)
            if base_account is None:
                raise Exception(
                    f'Could not find token account owned by {self.wallet.address}'
                    f'for base token {self.market.base}.'
                )
            quote_account = mango.TokenAccount.fetch_largest_for_owner_and_token(
                self.context, self.wallet.address, self.market.quote)
            if quote_account is None:
                raise Exception(
                    f'Could not find token account owned by {self.wallet.address}'
                    'for quote token {self.market.quote}.'
                )
            return [base_account.value, quote_account.value]
        else:
            group = mango.Group.load(self.context)
            accounts = mango.Account.load_all_for_owner(self.context, self.wallet.address, group)
            if len(accounts) == 0:
                raise Exception("No Mango account found.")

            account = accounts[0]
            return account.net_values

    def calculate_order_prices(self):

        self.logger.info(f"Price is: {self.model.oracle_price.latest}")

        alpha = self.cfg.oracle_coefs[0]

        if alpha < 1:
            self.logger.info(
                f'Current best prices are: bid={self.model.orderbook.latest.top_bid},'
                f' ask={self.model.orderbook.latest.top_ask}'
            )
            book_mid = (
                self.model.orderbook.latest.top_bid.price
                + self.model.orderbook.latest.top_ask
            ) / 2

        else:
            book_mid = 0

        # CHKP TODO oracle_price is not a type Watcher and it has never been, does it work this way?
        oracle_mid = self.model.oracle_price.latest.mid_price

        fair_price = alpha * oracle_mid + (1 - alpha) * book_mid

        bid = fair_price * (1 - self.spread_ratio)
        ask = fair_price * (1 + self.spread_ratio)

        return bid, ask

    def calculate_order_quantities(
            self,
            inventory: typing.Sequence[typing.Optional[mango.InstrumentValue]],
            current_orders: typing.Sequence[mango.Order]
    ):
        """
        Quotes

           position_size_ratios ((leverage - 1) bankroll + position)

        position can be negative
        bankroll is the sum of positions, i.e. how much funds do we have on the account
        """
        price = self.model.oracle_price.latest

        base_tokens: typing.Optional[mango.InstrumentValue] = mango.InstrumentValue.find_by_token(
            inventory, price.market.base
        )
        if base_tokens is None:
            raise Exception(
                f"Could not find market-maker base token {price.market.base.symbol} in inventory."
            )

        quote_tokens: typing.Optional[mango.InstrumentValue] = mango.InstrumentValue.find_by_token(
            inventory, price.market.quote
        )
        if quote_tokens is None:
            raise Exception(
                f"Could not find market-maker quote token {price.market.quote.symbol} in inventory."
            )

        self.logger.info('Current orders: %s', [order for order in current_orders])
        self.logger.info('base_tokens: %s, quote_tokens: %s', base_tokens, quote_tokens)
        total_available_base = base_tokens.value + sum([
            order.quantity for order in current_orders if order.side == mango.Side.SELL
        ])
        total_available_quote = quote_tokens.value / price.mid_price + sum([
            order.quantity for order in current_orders if order.side == mango.Side.BUY
        ])

        total_available = (total_available_base + total_available_quote)
        leveraged_available = (self.cfg.leverage - 1) * total_available

        self.logger.info(
            'total_available_base(sell)=%s,'
            ' total_available_quote(buy)=%s,'
            ' leveraged_available(total)=%s',
            total_available_base,
            total_available_quote,
            leveraged_available,
        )

        # In case of SOL/USDC
        # If we have enough quote token (USDC), we want to exchange it for SOL -> we want to
        # quote bid(buy) and vise versa.

        buy_quantity = floor_quote(
            self.position_size_ratios[0],
            leveraged_available + total_available_quote,
            self.cfg.min_quote_size
        )
        if buy_quantity < self.cfg.min_quote_size:
            buy_quantity = Decimal('0')

        sell_quantity = floor_quote(
            self.position_size_ratios[1],
            leveraged_available + total_available_base,
            self.cfg.min_quote_size
        )
        if sell_quantity < self.cfg.min_quote_size:
            sell_quantity = Decimal('0')

        self.logger.info('Target quoted quantity: BUY: %s, SELL: %s', buy_quantity, sell_quantity)
        return buy_quantity, sell_quantity

    def orders_require_action(
        self,
        orders: typing.Sequence[mango.Order],
        price: Decimal,
        quantity: Decimal
    ) -> bool:
        """
        If there are not orders (orders is empty) or at least one order requires update
        (based on quantity or price) return True.
        """
        def within_tolerance(target_value, order_value, tolerance):
            tolerated = order_value * tolerance
            return (
                order_value < (target_value + tolerated)
            ) and (
                order_value > (target_value - tolerated)
            )
        return len(orders) == 0 or not all([
            within_tolerance(price, order.price, self.existing_order_tolerance)
            and within_tolerance(quantity, order.quantity, self.existing_order_tolerance)
            for order in orders
        ])

    def update_health_on_successful_iteration(self) -> None:
        try:
            Path(self.health_filename).touch(mode=0o666, exist_ok=True)
        except Exception as exception:
            self.logger.warning(
                f"Touching file '{self.health_filename}' raised exception: {exception}"
            )

    def __str__(self) -> str:
        return f"""« 𝚂𝚒𝚖𝚙𝚕𝚎𝙼𝚊𝚛𝚔𝚎𝚝𝙼𝚊𝚔𝚎𝚛 for market '{self.market.symbol}' »"""

    def __repr__(self) -> str:
        return f"{self}"
