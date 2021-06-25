import argparse
import dataclasses
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from json import JSONEncoder
from logging import StreamHandler, LogRecord
from typing import Any, Optional, Mapping, Dict, Union, Callable, Set

import numpy as np
from config.helpers import AttributeDict
from sqlalchemy import Table, column
from sqlalchemy.orm import Session

import mango

FORMATTER = logging.Formatter(
    fmt='%(asctime)s.%(usec)s %(levelname)s %(name)s %(message)s %(extra_json)s',
    datefmt='%b %d %H:%M:%S'
)


class UsecFilter(logging.Filter):

    def filter(self, record: logging.LogRecord) -> int:
        record.usec = str(record.created - int(record.created))[2:8]
        return 1


class AdvancedJSONEncoder(JSONEncoder):
    def default(self, o):

        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)

        if isinstance(o, Exception):

            if isinstance(o.args, tuple):
                args = list(o.args)
            else:
                args = o.args

            return dict(exception=o.__class__.__name__, args=args)

        if isinstance(o, datetime):
            return o.strftime('%Y %b %d %H:%M:%S.%f')

        if isinstance(o, bytes):
            return o.hex()

        if isinstance(o, AttributeDict):
            return o.__dict__

        if isinstance(o, np.int64):
            return int(o)

        if isinstance(o, np.bool_):
            return bool(o)

        if isinstance(o, timedelta):
            return o.total_seconds()

        if isinstance(o, Decimal):
            return str(o)

        if isinstance(o, Enum):
            return str(o)

        if isinstance(o, Ticket):
            if o.is_filled():
                return o.get()
            else:
                return None

        try:
            return f'Non-serializable: {type(o)}: {str(o)}'
        except:  # noqa: E722
            return f'Totaly non-serializable data of type {(type(o))}'


class ExtraJsonFilter(logging.Filter):

    def filter(self, record: logging.LogRecord) -> int:
        record.extra_json = self._serialize(record.extra) if hasattr(record, 'extra') else "-"
        return 1

    def _serialize(self, data):

        if data:
            return f'# {json.dumps(data, cls=AdvancedJSONEncoder)}'

        return ''


@dataclasses.dataclass
class TableAdapter:
    table: Table
    individual_column_remappers: Dict[str, Callable]

    @staticmethod
    def create(inp: Union[Table, 'TableAdapter']):
        if inp is None:
            return None
        if isinstance(inp, TableAdapter):
            return inp
        if isinstance(inp, Table):
            return TableAdapter(table=inp, individual_column_remappers={})
        raise ValueError(f"Bad input: {inp}")


def _identity(x):
    return x


class DatabaseHandler(logging.Handler):

    def __init__(self, session: Session, table_map: Dict[str, Dict[str, Any]],
                 common_data: Dict[str, Union[Table, TableAdapter]], ticket_tables: Set[Table],
                 ticket_id_column: str, ticket_reference_column: str, debug_skipped):
        self._table_map = table_map
        self._common_data = common_data
        self._session = session
        self._debug_skipped = debug_skipped
        self._ticket_reference_column = ticket_reference_column
        self._ticket_tables = ticket_tables
        self._ticket_id_column = ticket_id_column
        super().__init__()

    def acquire(self) -> None:
        super().acquire()

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass

    def emit(self, record: logging.LogRecord) -> None:
        adapter = TableAdapter.create(
            self._table_map.get(record.name, {}).get(record.message, None)
        )
        if adapter is not None and hasattr(record, 'extra'):
            is_ticket_master = adapter.table in self._ticket_tables

            def adjust(k: str, v):
                if not is_ticket_master and k == self._ticket_reference_column:
                    return v.get()
                else:
                    return adapter.individual_column_remappers.get(k, _identity)(v)

            data = {
                "timestamp": datetime.utcfromtimestamp(record.created),
                **self._common_data,
                **{
                    k: adjust(k, v)
                    for k, v in (record.extra or {}).items()
                    if not (is_ticket_master and k == self._ticket_reference_column)
                }
            }
            cmd = adapter.table.insert(data).returning(column(self._ticket_id_column))
            res = self._session.execute(cmd)
            id = next(res)[self._ticket_id_column]
            if is_ticket_master:
                ticket: Ticket = record.extra[self._ticket_reference_column]
                ticket.fill(id)
        elif self._debug_skipped:
            print(f"SKIPPING: {record.message}")


def _create_make_record_wrapper(original_make_record):
    def make_record(name, level, fn, lno, msg, args, exc_info, func=None, extra=None, sinfo=None):
        return original_make_record(
            name, level, fn, lno, msg, args, exc_info, func,
            {"extra": extra}, sinfo
        )
    return make_record


class CustomLogger(logging.Logger):

    def makeRecord(self, name: str, level: int, fn: str, lno: int, msg: Any, args,
                   exc_info, func: Optional[str] = ...,
                   extra: Optional[Mapping[str, Any]] = ...,
                   sinfo: Optional[str] = ...) -> LogRecord:
        return super().makeRecord(
            name, level, fn, lno, msg, args, exc_info, func, {"extra": extra}, sinfo
        )


def remove_stream_handlers(logger: logging.Logger):
    for handler in logger.handlers:
        if isinstance(handler, StreamHandler):
            logger.removeHandler(handler)


class Ticket:
    id: Optional = None

    def is_filled(self):
        return self.id is not None

    def fill(self, value):
        if self.is_filled():
            raise Exception('Cannot fill a ticket that is already filled')
        if value is None:
            raise ValueError('Cannot fill with None')
        self.id = value

    def get(self):
        if not self.is_filled():
            raise Exception('Ticket has not been filled')
        return self.id


def setup_logging(args: argparse.Namespace, set_loglevel_from_args: bool,
                  set_notifications_from_args: bool):
    logger = logging.getLogger()
    if set_loglevel_from_args:
        logger.setLevel(args.log_level)
    remove_stream_handlers(logger)
    logger.addFilter(UsecFilter())
    logger.addFilter(ExtraJsonFilter())
    ch = logging.StreamHandler()
    ch.setFormatter(FORMATTER)
    ch.addFilter(UsecFilter())
    ch.addFilter(ExtraJsonFilter())
    logger.addHandler(ch)
    # The root logger has already been initialized…
    original_make_record = logger.makeRecord
    logger.makeRecord = _create_make_record_wrapper(original_make_record)

    logging.warning(mango.WARNING_DISCLAIMER_TEXT)

    if set_notifications_from_args:
        for notify in args.notify_errors:
            handler = mango.NotificationHandler(notify)
            handler.setLevel(logging.ERROR)
            logging.getLogger().addHandler(handler)


logging.setLoggerClass(CustomLogger)  # Calling this in setup_logging is too late.
