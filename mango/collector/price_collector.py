#!/usr/bin/env pyston3

import argparse
import collections
import datetime
import json
import logging
import lzma
import os
import signal
import threading
import time
import traceback
import typing

from threading import Thread

import mango  # nopep8
from mango.main_thread_exceptions import wrap_main
from mango.types_ import Configuration
from mango import Context, Price, InventorySource
from mango.oracles.ftx.ftx import FtxOracle
from mango.oracles.pythnetwork.pythnetwork import PythOracleProvider
from mango.oracles.raydium.raydium import RaydiumTradeCollectorProvider, RaydiumTradeCollector
from mango.configuration import load_configuration
from mango.heartbeat import heartbeat, heartbeat_init


LOGGER = logging.getLogger()
LOGGER.setLevel(logging.DEBUG)
logging.getLogger("urllib3").setLevel(logging.WARNING)

def parse_args(args=None):

    parser = argparse.ArgumentParser(description='Periodically collects oracle prices.')
    parser.add_argument('config', type=str, nargs=1, help='Which configuration to use')
    mango.ContextBuilder.add_command_line_parameters(parser)

    return parser.parse_args(args)


class MyEncoder(json.JSONEncoder):
    def default(self, o):
        return o.__dict__()


class Collector:
    def __init__(
            self,
            oracles: typing.Dict[str, typing.Dict[str, mango.Oracle]],
            context: Context,
            cfg: Configuration,
            logger: logging.Logger
    ) -> None:
        """
        The structure of oracles is:
        - on first level we have oracle name (FTX)
        - on second level we have symbol name (SOL/USDT)
        - leaf is oracle it self
        """
        self.oracles = oracles
        self.context = context
        self.logger = logger

        self.pause_duration = cfg.price_collector.pause_duration
        self.max_number_of_observations = cfg.price_collector.max_number_of_observations
        self.target_dir = cfg.paths.datadir
        self.server_name = cfg.price_collector.server_name
        self.heartbeat_filepath = cfg.paths.price_collector_heartbeat

        # number of observations per file
        self.number_of_observations: typing.Dict[str, typing.Dict[str, int]] = {
            oracle_name: {
                symbol: 0
                for symbol in oracle_all_symbols.keys()
            }
            for oracle_name, oracle_all_symbols in oracles.items()
        }
        self.stop_requested = False

        self.opened_files: typing.Dict[str, typing.Dict[str, typing.Optional[typing.TextIO]]] = {
            oracle_name: {
                symbol: None
                for symbol in oracle_all_symbols.keys()
            }
            for oracle_name, oracle_all_symbols in oracles.items()
        }

    def start(self) -> typing.Dict[str, Price]:
        """
        Iteratively add price observation to a file as json lines.
        When enough data are added to the file, it is closed and new one opened.

        TBD:
        - in case of FTX we can use websocket connection
        - in case of FTX we can request all of the data at once
        - in case of RAYDIUM_trades we can download all of the prices
        """
        while not self.stop_requested:
            last_iteration = time.time()

            self._heartbeat()

            for oracle_name, oracle_all_symbols in self.oracles.items():
                for symbol, oracle in oracle_all_symbols.items():
                    try:
                        if isinstance(oracle, RaydiumTradeCollector):
                            prices = oracle.batch_fetch_prices(self.context)
                            self.record_observations(prices, oracle_name, symbol)
                        else:
                            price = oracle.fetch_price(self.context)
                            self.record_observation(price, oracle_name, symbol)
                    except Exception as e:
                        # Using bare exception since some oracles "raise Exception"
                        self.logger.warning(f'Failed fetching price for {oracle_name}, {symbol}.')
                        self.logger.error(e)
            time.sleep(max(0, self.pause_duration - (time.time() - last_iteration)))

    def record_observation(self, price: Price, oracle_name: str, symbol: str) -> None:
        """Add observation to a file."""
        self.logger.debug(
            'Recording new observation to file. %s, %s, %s', oracle_name, symbol, price
        )

        # All files get closed at the same time -> it might get stuck here.
        if self.number_of_observations[oracle_name][symbol] >= self.max_number_of_observations:
            self.close_file(oracle_name, symbol)
            self.number_of_observations[oracle_name][symbol] = 0

        if self.opened_files[oracle_name][symbol] is None:
            self.open_file(oracle_name, symbol)

        self.opened_files[oracle_name][symbol].write(
            json.dumps(price, cls=MyEncoder).encode('utf-8')
        )
        self.opened_files[oracle_name][symbol].write('\n'.encode('utf-8'))

        self.number_of_observations[oracle_name][symbol] += 1

    def record_observations(
        self,
        prices: typing.List[Price],
        oracle_name: str,
        symbol: str
    ) -> None:
        """Add observations to a file."""
        for price in prices:
            self.record_observation(price, oracle_name, symbol)

    def open_file(self, oracle_name: str, symbol: str) -> None:
        data_type = 'oracle' if oracle_name != 'RAYDIUM_trades' else 'trade'

        dir_path = os.path.join(
            self.target_dir,
            oracle_name,
            self.server_name,
            symbol.replace('/', '-'),
            data_type
        )
        os.makedirs(dir_path, exist_ok=True)
        filename = datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S') + '.js.xz'
        filepath = os.path.join(dir_path, filename)
        increment = 0
        while os.path.exists(filepath):
            increment += 1
            incremented_filename = filename.replace('.js.xz', f'_{increment}.js.xz')
            filepath = os.path.join(dir_path, incremented_filename)

        self.opened_files[oracle_name][symbol] = lzma.open(filepath, 'w')
        self.logger.info(f'Created new file for prices {filepath}.')

    def close_file(self, oracle_name: str, symbol: str) -> None:
        opened_file = self.opened_files.get(oracle_name, {}).get(symbol, None)

        if opened_file is not None:
            opened_file.close()
            self.opened_files[oracle_name][symbol] = None

        self.logger.info('Closed (saved) file for prices. For %s, %s', oracle_name, symbol)

    def close_files(self) -> None:
        for oracle_name in self.oracles.keys():
            for symbol in self.oracles[oracle_name].keys():
                self.close_file(oracle_name, symbol)

    def stop(self):
        self.logger.info("Stop requested.")
        self.close_files()
        self.stop_requested = True

    def _heartbeat(self) -> None:
        self.logger.info(f'Heart beating {self.heartbeat_filepath}.')
        heartbeat(self.heartbeat_filepath)


def main(args: argparse.Namespace) -> None:
    try:
        cfg = load_configuration(args.config[0])
        heartbeat_init(cfg.paths.price_collector_heartbeat)
        args.cluster_url = cfg.account.cluster_url
        context = mango.ContextBuilder.from_command_line_parameters(args)

        def get_oracle(
            cfg: Configuration,
            oracle_name: str,
            symbol: str
        ) -> typing.Optional[mango.Oracle]:
            market = context.market_lookup.find_by_symbol(symbol)
            if market is None:
                market = collections.namedtuple(
                    'XXX',
                    ['symbol', 'inventory_source']
                )(symbol, InventorySource.ACCOUNT)

            if oracle_name == 'FTX':
                return FtxOracle(market, symbol.upper(), cfg)
            elif oracle_name == 'PYTH':
                pyth_oracle_provider = PythOracleProvider(context, cfg)
                return pyth_oracle_provider.oracle_for_market(context, market)
            elif oracle_name == 'RAYDIUM_trades':
                raydium_oracle_provider = RaydiumTradeCollectorProvider()
                return raydium_oracle_provider.trade_collector_for_market(context, market)

            raise NotImplementedError(f'Oracle {oracle_name} is not yet implemented.')

        oracles = {
            oracle_name: {
                symbol: get_oracle(cfg, oracle_name, symbol)
                for symbol in symbols
            }
            for oracle_name, symbols in cfg.price_collector.symbols.items()
        }
        # removing None values
        oracles = {
            oracle_name: {
                symbol: oracle
                for symbol, oracle in symbols.items()
                if oracle is not None
            }
            for oracle_name, symbols in oracles.items()
        }

        collector = Collector(
            oracles,
            context,
            cfg,
            LOGGER
        )
        thread = Thread(target=collector.start)
        thread.start()

        # Wait - don't exit. Exiting will be handled by signals/interrupts.
        waiter = threading.Event()
        signal.signal(signal.SIGTERM, lambda: waiter.set())
        try:
            waiter.wait()
        except:  # noqa: E722
            pass

        LOGGER.info("Stopping on next iteration...")
        collector.stop()
    except Exception as exception:
        logging.critical(
            "Price collector stopped because of exception: %s - %s",
            exception, traceback.format_exc()
        )
    except:  # noqa: E722
        logging.critical(
            "Price collector stopped because of uncatchable error: %s",
            traceback.format_exc()
        )


if __name__ == '__main__':
    wrap_main(lambda: main(parse_args()))
