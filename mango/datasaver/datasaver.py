import logging
import rx
import rx.subject
import json

from pathlib import Path
from io import TextIOWrapper
from time import time_ns
from mango.observables import EventSource


class DataSaver(rx.core.Observer):
    file_path: Path
    publisher: EventSource[str]

    def __init__(self, filename: str):
        self.__logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.__data_file: TextIOWrapper = None

        self.publisher = EventSource[str]()

        if filename == None:
            raise ValueError('DataSaver expects "filename" argument being provided')

        self.file_path = Path(filename)
        file_path_dir = self.file_path.parent.resolve()
        file_path_dir.mkdir(exist_ok=True, parents=True)

        self.__logger.info(f'Opening data file for watching {self.file_path}')
        self.__data_file = open(self.file_path, mode = 'a', encoding = 'utf-8')
        self.publisher.subscribe(self)


    def close(self) -> None:
        if self.__data_file is not None:
            self.__data_file.close()


    def on_next(self, data: any) -> None:
        self.__logger.info("Processing some data...")
        data = {'timestamp': time_ns(), 'data': str(data)}
        json.dump(data, self.__data_file)
        self.__data_file.write('\n')


    def on_error(self, ex: Exception) -> None:
        # TODO: handle errors
        self.__logger.error(f'Error on processing DataSaving {ex}')
        pass


    def on_completed(self) -> None:
        self.__logger.info(f'DataSaver for file {self.file_path} finished')
        pass
