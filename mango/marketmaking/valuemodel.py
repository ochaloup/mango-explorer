from typing import TypeVar, Generic
import logging

from mango.marketmaking.modelstate import ModelState, ModelStateValues


T = TypeVar('T')
S = TypeVar('S')


class ValueModel(Generic[T]):
    def __init__(self, cfg: T):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.cfg = cfg

    def eval(self, model_state: ModelState) -> ModelStateValues:
        raise NotImplementedError()
