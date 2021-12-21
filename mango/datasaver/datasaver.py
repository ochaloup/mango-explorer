from __future__ import annotations  # PEP563 posponed evaluation

import logging
import rx
import rx.subject
import simplejson as json
import solana

from enum import Enum
from pathlib import Path
from io import TextIOWrapper
from time import time_ns
from typing import List


# JSON fields
_JSON_TYPE = 'type'
_JSON_SAVE_TIMESTAMP = 'timestamp'
_JSON_DATA = 'data'


class DataTypes(Enum):
    unknown = 'unknown'
    bids = 'bids'


class DataSaver:
    file_path: Path
    data_file: TextIOWrapper
    observers: List[_DataSaverObserver]

    def __init__(self, filename: str):
        self.__logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.data_file: TextIOWrapper = None

        if filename is None:
            raise ValueError('DataSaver expects "filename" argument being provided')

        self.file_path = Path(filename)
        file_path_dir = self.file_path.parent.resolve()
        file_path_dir.mkdir(exist_ok=True, parents=True)
        self.__logger.info(f'Opening data file for watching {self.file_path}')
        self.__data_file = open(self.file_path, mode='a', encoding='utf-8')

    def close(self) -> None:
        for v in self.observers:
            v.dispose()
        if self.__data_file is not None:
            self.__data_file.close()

    def new_observer(self, data_type: DataTypes):
        observer_created = _DataSaverObserver(self, data_type)
        self.observers.append(observer_created)
        return observer_created


class _DataSaverObserver(rx.core.Observer):
    def __init__(self, data_saver: DataSaver, data_type: DataTypes):
        self.data_type = data_type
        self.data_saver = data_saver

    def on_next(self, data: any) -> None:
        print(f'>>> {type(data)}')  # TODO: DELETE ME

        data_encriched = {
            _JSON_TYPE: str(self.data_type),
            _JSON_SAVE_TIMESTAMP: time_ns(),
            _JSON_DATA: data
        }
        json.dump(
            data_encriched,
            self.__data_file,
            separators=(",", ":"),
            cls=_MangoDataSaverJSONEncoder
        )
        self.__data_file.write('\n')

    def on_error(self, ex: Exception) -> None:
        # TODO: handle errors
        self.__logger.error(f'Error on processing DataSaving {ex}')
        pass

    def on_completed(self) -> None:
        self.__logger.info(f'DataSaver for file {self.file_path} finished')
        pass


class _MangoDataSaverJSONEncoder(json.JSONEncoder):
    def default(self, o):

        if isinstance(o, Enum):
            return str(o)

        elif isinstance(o, solana.publickey.PublicKey):
            return str(o)  # String representation in base58 form

        else:
            super(_MangoDataSaverJSONEncoder, self).default(o)
