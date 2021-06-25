import argparse
import datetime
import logging

from mango.configuration import load_configuration
import requests
from sqlalchemy import create_engine
from sqlalchemy import Table, Column, DateTime, String, MetaData


NAME = 'orca_apy'

LOGGER = logging.getLogger()
LOGGER.setLevel(logging.DEBUG)


def parse_args(args=None):

    parser = argparse.ArgumentParser(description='Periodically collects oracle prices.')
    parser.add_argument('config', type=str, nargs=1, help='Which configuration to use')

    return parser.parse_args(args)


def fetch_pools_data() -> dict:
    url = 'https://api.orca.so/allpools'
    resp = requests.get(url)
    return resp.json()


def make_db_sink(cfg):

    engine = create_engine(cfg.dashboard_url)

    collection = MetaData()
    table = Table(
        NAME,
        collection,
        Column('timestamp', DateTime),
        Column('pool_name', String),
        Column('apy_day', String),
        Column('apy_week', String),
        Column('apy_month', String),
    )
    table.create(engine, checkfirst=True)

    db = engine.connect()
    stmt = table.insert()

    def insert(record):
        return db.execute(stmt, record)

    return insert


def main(args: argparse.Namespace) -> None:
    cfg = load_configuration(args.config[0])
    sink = make_db_sink(cfg.database)
    pools_data = fetch_pools_data()
    LOGGER.info(f'Retrieved data about {len(pools_data)} pools')

    now = datetime.datetime.utcnow()
    for (pool_name, data) in pools_data.items():
        apy = data['apy']
        sink(dict(
            timestamp=now,
            pool_name=pool_name,
            apy_day=apy.get('day', ''),
            apy_week=apy.get('week', ''),
            apy_month=apy.get('month', '')
        ))


if __name__ == '__main__':
    args = parse_args()
    main(args)
