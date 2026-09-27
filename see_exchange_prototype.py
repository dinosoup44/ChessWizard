"""Compatibility names for old research scripts; all calculation lives in the toolkit.

New callers import board_analysis.static_exchange. These aliases deliberately do
not preserve the retired research provenance tag or duplicate exchange logic.
"""
from board_analysis.static_exchange import (
    ExchangeStep,
    StaticExchangePolicy as ExchangePolicy,
    StaticExchangeResult as StaticExchangeEvaluation,
    evaluate_static_exchange as see_exchange,
)

__all__ = ["ExchangeStep", "ExchangePolicy", "StaticExchangeEvaluation", "see_exchange"]
