"""The retired research entry point must remain an alias, never a second algorithm."""
import unittest
import see_exchange_prototype as research
from board_analysis.static_exchange import (
    evaluate_static_exchange, StaticExchangePolicy, StaticExchangeResult, ExchangeStep,
)


class ResearchCompatibilityTests(unittest.TestCase):
    def test_old_names_are_shared_objects(self):
        self.assertIs(research.see_exchange, evaluate_static_exchange)
        self.assertIs(research.ExchangePolicy, StaticExchangePolicy)
        self.assertIs(research.StaticExchangeEvaluation, StaticExchangeResult)
        self.assertIs(research.ExchangeStep, ExchangeStep)
