import argparse
import logging
from signal import signal, SIGQUIT, SIGINT, SIGTERM, SIGUSR1
import sys
import threading
import traceback

import rx
import rx.operators as rxop

from decimal import Decimal

import mango
import mango.marketmaking
from mango.main_thread_exceptions import wrap_main
from mango.marketmaking.modelvalues import ModelValuesGraph
from mango.marketmaking.orderchain.chain import Chain
from mango.marketmaking.orderchain.chainbuilder import get_simple_orderchain
from mango.configuration import load_configuration
from mango.orders import OrderType


# TODO.  Don't forget about the redeem_threshold functionality.
# TODO.  Implement hedging functionality.  See Hedger.


def dumpstacks(signal, frame):

    id2name = dict([(th.ident, th.name) for th in threading.enumerate()])
    code = []
    for threadId, stack in sys._current_frames().items():

        code.append("\n# Thread: %s(%d)" % (id2name.get(threadId, ""), threadId))
        for filename, lineno, name, line in traceback.extract_stack(stack):

            code.append('File: "%s", line %d, in %s' % (filename, lineno, name))

            if line:
                code.append("  %s" % (line.strip()))

    print("\n".join(code))


def parse_args(args=None):

    parser = argparse.ArgumentParser(description="Runs a marketmaker against a particular market.")
    parser.add_argument('config', type=str, help='Which configuration to use')
    mango.ContextBuilder.add_command_line_parameters(parser)
    mango.Wallet.add_command_line_parameters(parser)
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true", default=False,
        help="runs as read-only and does not perform any transactions"
    )

    return parser.parse_args()


def cleanup(
        context: mango.Context,
        wallet: mango.Wallet,
        account: mango.Account,
        market: mango.Market,
        dry_run: bool
):
    market_operations: mango.MarketOperations = mango.create_market_operations(
        context, wallet, account, market, dry_run)
    builder: mango.MarketInstructionBuilder = \
        mango.create_market_instruction_builder(context, wallet, account, market, dry_run)
    cancels: mango.CombinableInstructions = mango.CombinableInstructions.empty()
    orders = market_operations.load_my_orders()
    for order in orders:
        cancels += builder.build_cancel_order_instructions(order, ok_if_missing=True)

    if len(cancels.instructions) > 0:
        logging.info(f"Cleaning up {len(cancels.instructions)} order(s).")
        signer: mango.CombinableInstructions = mango.CombinableInstructions.from_wallet(wallet)
        (signer + cancels).execute(context)
        market_operations.crank()
        market_operations.settle()


def override_args(cfg, args):
    args.cluster_url = cfg.account.cluster_url
    args.account_index = 0  # index of the account to use, if more than one available
    args.confidence_interval_level = cfg.marketmaker.confidence_interval_level
    args.position_size_ratios = cfg.marketmaker.position_size_ratios
    args.order_type = OrderType.POST_ONLY
    args.update_mode = mango.marketmaking.ModelUpdateMode.WEBSOCKET
    args.quote_position_bias = Decimal()
    args.minimum_charge_ratio = cfg.marketmaker.spread_ratio
    args.redeem_threshold = Decimal(100)  # move MNGO reward to the wallet automatically
    args.pulse_interval = cfg.marketmaker.poll_interval_seconds
    args.event_queue_poll_interval = cfg.marketmaker.poll_interval_seconds
    args.max_price_slippage_factor = Decimal("0.05")


def setup_logging(args):

    logging.getLogger().setLevel(logging.INFO)
    logging.warning(mango.WARNING_DISCLAIMER_TEXT)

    # CHKP TODO
    # for notify in args.notify_errors:
    #    handler = mango.NotificationHandler(notify)
    #    handler.setLevel(logging.ERROR)
    #    logging.getLogger().addHandler(handler)


def main():

    args = parse_args()
    cfg = load_configuration(args.config)
    override_args(cfg, args)

    setup_logging(args)

    exit_waiter = threading.Event()

    def handle_exit(signal, frame):
        dumpstacks(signal, frame)
        exit_waiter.set()
    signal(SIGTERM, handle_exit)
    signal(SIGQUIT, handle_exit)
    signal(SIGINT, handle_exit)

    def thread_exception_handler(args, /):
        traceback.print_exc()
        exit_waiter.set()  # When a thread fails, make the main thread to exit
    threading.excepthook = thread_exception_handler

    context = mango.ContextBuilder.from_command_line_parameters(args)
    logging.info(f"{context}")
    wallet = mango.Wallet.from_command_line_parameters(args) \
        or mango.Wallet.load(cfg.account.key_file)
    group = mango.Group.load(context, context.group_address)
    try:
        account = mango.Account.load_for_owner_by_address(
            context,
            wallet.address,
            group,
            None
        )
    except Exception as e:
        logging.error(f'Could not find any Mango accounts for owner {wallet.address}: {e}')
        account = None

    market_symbol = cfg.marketmaker.pair
    market = context.market_lookup.find_by_symbol(market_symbol)
    disposer = mango.DisposePropagator()
    try:
        manager = mango.IndividualWebSocketSubscriptionManager(context)
        disposer.add_disposable(manager)
        health_check = mango.HealthCheck(cfg.paths.trader_heartbeat_dir)
        disposer.add_disposable(health_check)

        if market is None:
            raise Exception(f"Could not find market {market_symbol}")

        # The market index is also the index of the base token in the group's token list.
        if market.quote != group.shared_quote_token:
            raise Exception(
                f"Group {group.name} uses shared quote token"
                f" {group.shared_quote_token.token.symbol}/{group.shared_quote_token.mint},"
                f" but market {market.symbol} uses"
                f" quote token {market.quote.symbol}/{market.quote.mint}."
            )

        cleanup(context, wallet, account, market, args.dry_run)

        market = mango.ensure_market_loaded(context, market)
        # They should be decimals already, but they are not
        order_reconciler = mango.marketmaking.ToleranceOrderReconciler(
            Decimal(cfg.marketmaker.existing_order_price_tolerance),
            Decimal(cfg.marketmaker.existing_order_quantity_tolerance),
        )

        market_operations: mango.MarketOperations = \
            mango.create_market_operations(
                context,
                wallet,
                account,
                market,
                args.dry_run
            )

        is_perp = isinstance(market, mango.PerpMarket)
        desired_orders_chain: Chain = get_simple_orderchain(cfg.marketmaker, is_perp)
        model_values_graph = ModelValuesGraph(cfg.marketmaker, is_perp)
        market_instruction_builder: mango.MarketInstructionBuilder = \
            mango.create_market_instruction_builder(context, wallet, account, market, args.dry_run)
        market_maker = mango.marketmaking.MarketMaker(
            wallet,
            market,
            market_operations,
            market_instruction_builder,
            desired_orders_chain,
            model_values_graph,
            order_reconciler,
            args.redeem_threshold
        )

        model_state_builder: mango.marketmaking.ModelStateBuilder = \
            mango.marketmaking.model_state_builder_factory(
                cfg,
                args.update_mode,
                context,
                disposer,
                manager,
                health_check,
                wallet,
                group,
                account,
                market,
                cfg.marketmaker.oracle_providers
            )

        health_check.add("marketmaker_pulse", market_maker.pulse_complete)

        if account is not None:
            logging.info(f"Current assets in account {account.address} (owner: {account.owner}):")
            net_values = [net_value for net_value in account.net_values if net_value is not None]
            mango.InstrumentValue.report(net_values)

        manager.open()

        def on_next(_):
            return market_maker.pulse(
                context,
                model_state_builder.build(context)
            )

        pulse_disposable = rx.interval(cfg.marketmaker.poll_interval_seconds).pipe(
            rxop.observe_on(context.create_thread_pool_scheduler()),
            rxop.start_with(-1),
            rxop.catch(mango.observable_pipeline_error_reporter),
            rxop.retry()
        ).subscribe(on_next)

        disposer.add_disposable(pulse_disposable)

        # Wait - don't exit. Exiting will be handled by signals/interrupts.
        try:
            print('exit_waiter: wait')
            exit_waiter.wait()
            print('exit_waiter has been set')
        except:  # noqa: E722
            pass

    finally:
        logging.info("Shutting down...")
        disposer.dispose()
        cleanup(context, wallet, account, market, args.dry_run)
        logging.info("Shutdown complete.")


if __name__ == '__main__':
    signal(SIGUSR1, dumpstacks)
    wrap_main(main)
