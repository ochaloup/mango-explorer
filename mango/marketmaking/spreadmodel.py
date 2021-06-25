from mango.types_ import MarketMakerConfiguration
from mango.marketmaking.valuemodel import ValueModel
from mango.modelstate import ModelState, ModelStateValues


class FairSpreadModel(ValueModel[MarketMakerConfiguration]):
    def eval(self, model_state: ModelState):

        book_spread = model_state.values.book_spread

        fair_spread = max(
            self.cfg.spread_ratio,
            self.cfg.book_spread_coef * book_spread
        )

        self.logger.info(
            'eval()',
            extra=dict(book_spread=book_spread, fair_spread=fair_spread)
        )

        return ModelStateValues(fair_spread=fair_spread)
