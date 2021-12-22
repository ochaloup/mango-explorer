from __future__ import annotations  # PEP563 posponed evaluation

import logging
import rx
import rx.subject
import simplejson as json

import mango

from datetime import datetime
from enum import Enum
from pathlib import Path
from io import TextIOWrapper
from time import time_ns
from typing import List

from solana.publickey import PublicKey


# JSON fields
_JSON_TYPE = 'type'
_JSON_SAVE_TIMESTAMP = 'timestamp'
_JSON_DATA = 'data'


class DataSaverTypes(Enum):
    Unknown = 'unknown'
    Bids = 'bids'
    Asks = 'asks'
    Price = 'price'


class DataSaver:
    file_path: Path
    data_file: TextIOWrapper
    __observers: List[_DataSaverObserver] = []

    def __init__(self, filename: str):
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)

        if filename is None:
            raise ValueError('DataSaver expects "filename" argument being provided')

        self.file_path = Path(filename)
        file_path_dir = self.file_path.parent.resolve()
        file_path_dir.mkdir(exist_ok=True, parents=True)
        self.logger.info(f'Opening data file for watching {self.file_path}')
        self.data_file = open(self.file_path, mode='a', encoding='utf-8')

    def close(self) -> None:
        for v in self.__observers:
            v.dispose()
        if self.data_file is not None:
            self.data_file.close()

    def new_observer(self, data_type: DataSaverTypes):
        observer_created = _DataSaverObserver(self, data_type)
        self.__observers.append(observer_created)
        return observer_created


class _DataSaverObserver(rx.core.Observer):
    def __init__(self, data_saver: DataSaver, data_type: DataSaverTypes):
        self.data_type = data_type
        self.data_saver = data_saver

    def on_next(self, data: any) -> None:
        print(f'>>> {type(data)}')  # TODO: DELETE ME

        data_encriched = {
            _JSON_TYPE: self.data_type.value,
            _JSON_SAVE_TIMESTAMP: time_ns(),
            _JSON_DATA: data
        }
        json.dump(
            data_encriched,
            self.data_saver.data_file,
            separators=(",", ":"),
            cls=_MangoDataSaverJSONEncoder
        )
        self.data_saver.data_file.write('\n')

    def on_error(self, ex: Exception) -> None:
        # TODO: handle errors
        self.data_saver.logger.error(f'Error on processing DataSaving {ex}')
        pass

    def on_completed(self) -> None:
        self.data_saver.logger.info(f'DataSaver for file {self.file_path} finished')
        pass


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
                'bids': o.bids,
                'asks': o.asks
            }

        if isinstance(o, mango.oracle.Price):
            return {
                'source': o.source.provider_name,
                'timestamp': datetime.timestamp(o.timestamp),
                'market_base': o.market.base.name,
                'market_quote': o.market.quote.name,
                'market_address': o.market.address,
                'top_bid': o.top_bid,
                'top_ask': o.top_ask,
                'mid_price': o.mid_price,
                'confidence': o.confidence
            }

        if isinstance(o, PublicKey):
            return str(o)  # String representation in base58 form

        return json.JSONEncoder.default(self, o)
