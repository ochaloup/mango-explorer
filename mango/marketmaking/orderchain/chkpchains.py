import typing
from decimal import Decimal
import logging

import mango
from mango.types_ import MarketMakerConfiguration
from mango.marketmaking.orderchain.chain import Chain
from mango.marketmaking.orderchain.preventpostonlycrossingbookelement \
    import PreventPostOnlyCrossingBookElement
from mango.marketmaking.orderchain.chkpelements \
    import LeveragedFixedRatiosElement, LimitSpreadNarrowingElement, \
    ShalowOrdersOnlyElement, PreventCrossingElement, SimpleTakerElement
from mango import ModelState


# CHKP addition
def get_orderchain(
        cfg: MarketMakerConfiguration,
        is_perp: bool  # TODO: get this to modelstate once we get rid of order_tracker
) -> Chain:
    logging.info('Creating orderchain')
    if cfg.taker_min_profitability != Decimal('inf'):
        return get_orderchain_with_ioc(cfg, is_perp)
    return get_simple_orderchain(cfg, is_perp)


# CHKP addition
def get_simple_orderchain(
        cfg: MarketMakerConfiguration,
        is_perp: bool  # TODO: get this to modelstate once we get rid of order_tracker
) -> Chain:
    logging.info('Creating simple orderchain')
    return Chain([
        LeveragedFixedRatiosElement(
            cfg,
            is_perp,
        ),
        LimitSpreadNarrowingElement(cfg),
        PreventPostOnlyCrossingBookElement(),
        ShalowOrdersOnlyElement(cfg)
    ])


# CHKP addition
def get_orderchain_with_ioc(
        cfg: MarketMakerConfiguration,
        is_perp: bool  # TODO: get this to modelstate once we get rid of order_tracker
) -> Chain:
    logging.info('Creating orderchain with ioc')
    return Chain([
        ChainJoiner([
            get_simple_orderchain(cfg, is_perp),
            Chain([SimpleTakerElement(cfg, is_perp)])
        ]),
        PreventCrossingElement()
    ])


class ChainJoiner:

    """
    Joins chains.
    """

    def __init__(self, chains: typing.Sequence[Chain]) -> None:
        self._logger: logging.Logger = logging.getLogger(self.__class__.__name__)
        self.chains = chains

    def process(self, context: mango.Context, model_state: ModelState, _) -> typing.Sequence[mango.Order]:
        self._logger.info('Started processing ChainJoiner of chains')
        all_orders: typing.Sequence[mango.Order] = []
        for chain in self.chains:
            self._logger.info(f'Processing {chain} chain')
            all_orders += chain.process(context, model_state)

        return all_orders

    def __repr__(self) -> str:
        return f"{self}"

    def __str__(self) -> str:
        chains = ", ".join(map(str, self.chains)) or "None"

        return f"""Chain of {len(self.chains)} chains: {chains}"""
