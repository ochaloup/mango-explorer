from __future__ import annotations  # PEP563 posponed evaluation

import logging
import rx
import rx.subject
import simplejson as json
import lzma
import typing
import datetime

import mango

from enum import Enum
from pathlib import Path
from time import time_ns
from typing import List

from solana.publickey import PublicKey

# JSON fields
_JSON_CHAINKEEPERS_TIMESTAMP = 'chainkeepers_timestamp'
_JSON_DATA = 'data'


class DataSaverTypes(Enum):
    Unknown = 'unknown'
    OrderBook = 'orderbook'
    Price = 'price'
    OpenOrders = 'openorders'
    Account = 'account'


class DataSaver(rx.core.typing.Disposable):
    _observers: dict[DataSaverTypes, _DataSaverObserver] = {}

    def __init__(self, dirname: str, max_observations: int):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self._max_observations = max_observations

        if dirname is None:
            raise ValueError('DataSaver expects "dirname" argument being provided')

        self.data_dir = Path(dirname).resolve()
        self.data_dir.mkdir(exist_ok=True, parents=True)

    def dispose(self) -> None:
        for _, v in self._observers.items():
            v.dispose()

    def get_observer(self, data_type: DataSaverTypes) -> DataSaver:
        if data_type not in self._observers:
            observer_created = _DataSaverObserver(self, data_type)
            self._observers[data_type] = observer_created
        return self._observers[data_type]


class _DataSaverObserver(rx.core.Observer):
    def __init__(self, data_saver: DataSaver, data_type: DataSaverTypes):
        super().__init__()
        self.data_type = data_type
        self.data_saver = data_saver
        self._data_dir = data_saver.data_dir.joinpath(data_type.value)
        self._data_dir.mkdir(exist_ok=True, parents=True)
        self._data_file: lzma.LZMAFile = None
        self._data_file_path: Path = None
        self._last_data: str = ''
        self._observation_counter: int = 1
        self._open_new_file()

    def _on_next_core(self, data: any) -> None:
        # no data change from last execution, skipping to save
        json_string_data = self._dump_json(data)
        if json_string_data == self._last_data:
            return
        self._last_data = json_string_data

        data_enriched = {
            _JSON_CHAINKEEPERS_TIMESTAMP: time_ns(),
            _JSON_DATA: data
        }
        json_string_data_enriched = self._dump_json(data_enriched)
        self._write_data(json_string_data_enriched)

    def _on_error_core(self, ex: Exception) -> None:
        # TODO: consider handling the errors better; 2022 Jan
        self._close_data_file()
        self.data_saver.logger.exception(
            f'Error on processing data saver {self.data_type} at {self._data_file_path}: {ex}'
        )

    def _on_completed_core(self) -> None:
        self._close_data_file()

    def dispose(self) -> None:
        super().dispose()
        self._close_data_file()

    def _write_data(self, string_to_write: str) -> None:
        if self._observation_counter > self.data_saver._max_observations:
            self._open_new_file()
            self._observation_counter = 1
        self._data_file.write(string_to_write.encode('utf-8'))
        self._data_file.write('\n'.encode('utf-8'))
        self._observation_counter = self._observation_counter + 1

    def _open_new_file(self) -> None:
        new_data_file_path = self._data_dir.joinpath(datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S') + '.jl.xz')
        self.data_saver.logger.info(f'Opening data saver file for {self.data_type} at {new_data_file_path}')
        self._close_data_file()
        self._data_file_path = new_data_file_path
        self._data_file = lzma.open(new_data_file_path, mode='w')

    def _close_data_file(self) -> None:
        if self._data_file is not None:
            self.data_saver.logger.info(f'Closing data saver file {self._data_file_path}')
            self._data_file.close()
            self._data_file = None
            self._data_file_path = None

    def _dump_json(self, data: any) -> str:
        return json.dumps(
            data,
            separators=(",", ":"),
            encoding='utf-8',
            cls=_MangoDataSaverJSONEncoder
        )


class _MangoDataSaverJSONEncoder(json.JSONEncoder):
    def default(self, o):

        if isinstance(o, Enum):
            return str(o)

        if isinstance(o, mango.orders.OrderBook):
            return {
                'symbol': o.symbol,
                'top_bid': o.top_bid,
                'top_ask': o.top_ask,
                'mid_price': o.mid_price,
                'spread': o.spread,
                'bids': self._encode_order(o.bids),
                'asks': self._encode_order(o.asks)
            }

        if isinstance(o, mango.orders.Order):
            return {
                'id': o.id,
                'client_id': o.client_id,
                'owner': o.owner,
                'price': o.price,
                'quantity': o.quantity,
                'side': o.side,
                'order_type': o.order_type,
            }

        if isinstance(o, mango.oracle.Price):
            return {
                'top_bid': o.top_bid,
                'top_ask': o.top_ask,
                'mid_price': o.mid_price,
                'confidence': o.confidence,
                'source': o.source,
                'market': o.market,
                'timestamp': str(o.timestamp),
                'chainkeepers_timestamp': o.chainkeepers_timestamp
            }

        if isinstance(o, mango.oracle.OracleSource):
            return {
                'provider_name': o.provider_name,
                # 'source_name': o.source_name,
                # 'supports': o.supports
            }

        if isinstance(o, mango.oracle.Market):
            return {
                'base': o.base,
                'quote': o.quote,
                'lot_size_converter': o.lot_size_converter,
                'inventory_source': o.inventory_source.name,
                # 'program_address': o.program_address,
                # 'address': o.address,
            }

        if isinstance(o, mango.token.Instrument):  # Token: child of Instrument
            return {
                'symbol': o.symbol,
                # 'name': o.name,
                # 'decimals': o.decimals
            }

        if isinstance(o, mango.lotsizeconverter.LotSizeConverter):
            return {
                'base_lot_size': o.base_lot_size,
                'quote_lot_size': o.quote_lot_size
                # 'base': o.base,
                # 'quote': o.quote,
            }

        if isinstance(o, PublicKey):
            return str(o)  # String in base58

        if isinstance(o, mango.openorders.OpenOrders):
            return {
                'version': o.version,
                'program_address': o.program_address,
                'account_flags': o.account_flags,
                'market': o.market,
                'owner': o.owner,
                'base_token_free': o.base_token_free,
                'base_token_total': o.base_token_total,
                'quote_token_free': o.quote_token_free,
                'quote_token_total': o.quote_token_total,
                'placed_orders': o.placed_orders,
                'referrer_rebate_accrued': o.referrer_rebate_accrued
            }

        return json.JSONEncoder.encode(o)

    def _encode_order(self, order_list: typing.Sequence[mango.orders.Order]) -> List[dict]:
        result = []
        for o in order_list:
            result.append({
                'id': o.id,
                'side': o.side,
                'price': o.price,
                'quantity': o.quantity,
                # 'client_id': o.client_id
                # 'owner': o.owner
                # 'order_type': o.order_type
            })
        return result
