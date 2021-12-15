from mango.types_ import MarketMakerConfiguration
from mango.marketmaking.orderchain.chain import Chain
from mango.marketmaking.orderchain.preventpostonlycrossingbookelement \
    import PreventPostOnlyCrossingBookElement
from mango.marketmaking.orderchain.chkpelements \
    import LeveragedFixedRatiosElement, LimitSpreadNarrowingElement


# CHKP addition
def get_simple_orderchain(
        cfg: MarketMakerConfiguration,
        is_perp: bool  # TODO: get this to modelstate once we get rid of order_tracker
) -> Chain:
    return Chain([
        LeveragedFixedRatiosElement(
            cfg,
            is_perp,
        ),
        LimitSpreadNarrowingElement(cfg),
        PreventPostOnlyCrossingBookElement()
    ])
