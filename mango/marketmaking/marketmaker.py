# # ⚠ Warning
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT
# LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN
# NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#
# [🥭 Mango Markets](https://mango.markets/) support is available at:
#   [Docs](https://docs.mango.markets/)
#   [Discord](https://discord.gg/67jySBhxrg)
#   [Twitter](https://twitter.com/mangomarkets)
#   [Github](https://github.com/blockworks-foundation)
#   [Email](mailto:hello@blockworks.foundation)


import logging
import mango
import traceback
import typing

from datetime import datetime
from decimal import Decimal

from ..observables import EventSource
from .orderreconciler import OrderReconciler
from .orderchain.chain import Chain
from .modelvalues import ModelValuesGraph
from .ordertracker import OrderTracker


# # 🥭 MarketMaker class
#
# An event-driven market-maker.
#
class MarketMaker:
    def __init__(self, wallet: mango.Wallet, market: mango.Market,
                 market_operations: mango.MarketOperations,  # CHKP addition
                 market_instruction_builder: mango.MarketInstructionBuilder,
                 desired_orders_chain: Chain,
                 model_values_graph: ModelValuesGraph,  # CHKP addition
                 order_reconciler: OrderReconciler,
                 redeem_threshold: typing.Optional[Decimal],
                 order_tracker: OrderTracker) -> None:
        self._logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.wallet: mango.Wallet = wallet
        self.market: mango.Market = market
        self.market_instruction_builder: mango.MarketInstructionBuilder = market_instruction_builder
        self.desired_orders_chain: Chain = desired_orders_chain
        self.order_reconciler: OrderReconciler = order_reconciler
        self.redeem_threshold: typing.Optional[Decimal] = redeem_threshold

        # CHKP additions
        self.market_operations = market_operations
        self.model_values_graph = model_values_graph

        self.pulse_complete: EventSource[datetime] = EventSource[datetime]()
        self.pulse_error: EventSource[Exception] = EventSource[Exception]()

        self.buy_client_ids: typing.List[int] = []
        self.sell_client_ids: typing.List[int] = []

        self.order_tracker = order_tracker

    def pulse(self, context: mango.Context, model_state: mango.ModelState) -> None:
        try:
            self._logger.debug(f"[{context.name}] Pulse started with oracle price:\n    {model_state.prices}")

            self.order_tracker.update_on_orderbook(model_state)

            payer = mango.CombinableInstructions.from_wallet(self.wallet)

            # CHKP additions
            # desired_orders = self.desired_orders_chain.process(context, model_state)
            existing_orders = model_state.current_orders()
            self.order_tracker.update_on_existing_orders(existing_orders)
            self.model_values_graph.update_values(model_state, existing_orders)

            desired_orders = self.desired_orders_chain.process(
                context,
                model_state
            )

            # This is here to give the orderchain the chance to look at state and set `not_quoting`. Any
            # element in the orderchain can set this, rather than just return an empty list of desired
            # orders, knowing it won't be accidentally changed by subsequent elements returning orders.
            #
            # It also gives the opportunity to code outside the orderchain to set `not_quoting` if that
            # code has access to the `model_state`.
            if model_state.not_quoting:
                self._logger.info(f"[{context.name}] Market-maker not quoting - model_state.not_quoting is set.")
                return

            # CHKP deletion
            # existing_orders = model_state.current_orders()
            self._logger.debug(f"""Before reconciliation: all owned orders on current orderbook [{model_state.market.symbol}]:
    {mango.indent_collection_as_str(existing_orders)}""")

            reconciled = self.order_reconciler.reconcile(model_state, existing_orders, desired_orders)
            self._logger.debug(f"""After reconciliation
Keep:
    {mango.indent_collection_as_str(reconciled.to_keep)}
Cancel:
    {mango.indent_collection_as_str(reconciled.to_cancel)}
Place:
    {mango.indent_collection_as_str(reconciled.to_place)}
Ignore:
    {mango.indent_collection_as_str(reconciled.to_ignore)}""")

            to_be_tracked_cancelation = []
            cancellations = mango.CombinableInstructions.empty()
            # Perp markets have a CANCEL_ALL instruction that Spot and Serum markets don't. Use it if we can.
            if reconciled.cancelling_all and isinstance(self.market_instruction_builder, mango.PerpMarketInstructionBuilder):
                ids = [f"{ord.id} / {ord.client_id}" for ord in reconciled.to_cancel]
                self._logger.info(f"Cancelling all orders on {self.market.symbol} - currently {len(ids)}: {ids}")
                cancellations = self.market_instruction_builder.build_cancel_all_orders_instructions()
            else:
                for to_cancel in reconciled.to_cancel:
                    self._logger.info(f"Cancelling {self.market.symbol} {to_cancel}")
                    cancel = self.market_instruction_builder.build_cancel_order_instructions(
                        to_cancel, ok_if_missing=True)
                    cancellations += cancel
                    to_be_tracked_cancelation.append(to_cancel)

            to_be_tracked_placing = []
            place_orders = mango.CombinableInstructions.empty()
            for to_place in reconciled.to_place:
                # place orders only if on given side, there is no "waiting" order
                # if there is order in the book, we are most likely moving it
                if not self.order_tracker.get_side_orders_to_be_in_book(to_place.side):
                    desired_client_id: int = context.generate_client_id()
                    to_place_with_client_id = to_place.with_client_id(desired_client_id)

                    self._logger.info(f"Placing {self.market.symbol} {to_place_with_client_id}")
                    place_order = self.market_instruction_builder.build_place_order_instructions(to_place_with_client_id)
                    place_orders += place_order
                    to_be_tracked_placing.append(to_place_with_client_id)

            self._logger.info('OrderTracker is: %s', self.order_tracker)

            crank = self.market_instruction_builder.build_crank_instructions(model_state.accounts_to_crank)
            settle = self.market_instruction_builder.build_settle_instructions()

            redeem = mango.CombinableInstructions.empty()
            if self.redeem_threshold is not None and model_state.inventory.liquidity_incentives.value > self.redeem_threshold:
                redeem = self.market_instruction_builder.build_redeem_instructions()

            # Don't bother if we have no orders to change

            if len(cancellations.instructions) + len(place_orders.instructions) > 0:
                txs = (payer + cancellations + place_orders + crank + settle + redeem).execute(
                    context
                )
                self._logger.info(f'Pulse has sent the following txs: {txs}')

                self.order_tracker.update_on_reconcile(
                    to_place=to_be_tracked_placing,
                    to_cancel=to_be_tracked_cancelation
                )

            self.pulse_complete.on_next(datetime.now())

        except (mango.RateLimitException, mango.NodeIsBehindException, mango.BlockhashNotFoundException, mango.FailedToFetchBlockhashException) as common_exception:
            # Don't bother with a long traceback for these common problems.
            self._logger.error(f"[{context.name}] Market-maker problem on pulse: {common_exception}")
            self.pulse_error.on_next(common_exception)
        except Exception as exception:
            self._logger.error(f"[{context.name}] Market-maker error on pulse:\n{traceback.format_exc()}")
            self.pulse_error.on_next(exception)

    def settle(self, context: mango.Context) -> None:
        try:

            payer = mango.CombinableInstructions.from_wallet(self.wallet)
            settle = self.market_instruction_builder.build_settle_instructions()

            # CHKP - always settle, otherwise we don't know how to quote since
            # the inverntory is messed up.
            txs = (payer + settle).execute(context)

            self._logger.info(f'settle has sent the following txs: {txs}')

        except Exception as exception:
            self._logger.error(f"[{context.name}] Market-maker error on settle:\n{traceback.format_exc()}")
            self.pulse_error.on_next(exception)

    def __str__(self) -> str:
        return f"""« MarketMaker for market '{self.market.symbol}' »"""

    def __repr__(self) -> str:
        return f"{self}"
