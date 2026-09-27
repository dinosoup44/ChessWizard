"""Verified facts -> FeedbackContext -> deterministic FeedbackResult -> UI."""
from .context import FeedbackContextBuilder
from .generator import FeedbackGenerator
from .models import FeedbackContext, FeedbackFact, FeedbackResult
from .registry import DataTemplateProvider, FeedbackRegistry, TemplateProvider

__all__ = ["FeedbackContextBuilder", "FeedbackGenerator", "FeedbackContext", "FeedbackFact",
           "FeedbackResult", "DataTemplateProvider", "FeedbackRegistry", "TemplateProvider"]
