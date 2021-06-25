import os
from logging import getLogger

from .types_ import Configuration, AccountConfiguration, \
    PathsConfiguration, DatabaseConfiguration, \
    MarketMakerConfiguration, PriceCollectorConfiguration, \
    FillCollectorConfiguration, SimpleArbitrageConfiguration, \
    MarinadeStakingConfiguration

from config import config_from_toml, ConfigurationSet


def optional_section(config_class, data):
    return config_class(**data) if data is not None else None


def optional_multisection(config_class, data):
    if data is not None:
        return {
            k: config_class(**v)
            for k, v in data.items()
            if isinstance(v, dict)
        }

    else:
        return None


def load_configuration(location) -> Configuration:

    logger = getLogger('load_config()')

    PREFIX = os.getenv('PREFIX', '/srv')

    logger.info(f"loading configuration from '{location}'")

    overrides = config_from_toml(location, read_from_file=True)

    base_name = overrides.get('config.base')
    if base_name is not None:
        base_location = f'{os.path.dirname(location)}/{base_name}'
        logger.info(f"loading base configuration from '{base_location}'")
        data = ConfigurationSet(
            overrides,
            config_from_toml(base_location, read_from_file=True)
        )

    else:
        data = overrides

    paths = {
        k: f'{PREFIX}/{v}'
        for k, v in data['paths'].items()
    }
    cfg = Configuration(
        account=AccountConfiguration(**data['account']),
        paths=PathsConfiguration(**paths),
        database=DatabaseConfiguration(**data['database']),
        marketmaker=MarketMakerConfiguration(**data['marketmaker']),
        price_collector=optional_section(
            PriceCollectorConfiguration,
            data.get('price_collector')
        ),
        fill_collector=optional_section(
            FillCollectorConfiguration,
            data.get('fill_collector')
        ),
        simplearbitrage=optional_multisection(
            SimpleArbitrageConfiguration,
            data.get('simplearbitrage')
        ),
        saber_arbitrage=optional_multisection(
            SimpleArbitrageConfiguration,
            data.get('saber_arbitrage')
        ),
        marinade_staking=optional_section(
            MarinadeStakingConfiguration,
            data.get('marinade_staking')
        ),
    )

    return cfg
