"""Minimal lifecycle contract for a single-position factual analyzer."""
from typing import Protocol
from .models import MaterialFacts, PositionContext


class AnalyzerPlugin(Protocol):
    """Analyze explicit contexts without owning UI, engines, or core persistence."""

    def analyze(self, context: PositionContext) -> MaterialFacts:
        """Describe the supplied position using structured, checkable facts.

        Args:
            context: Immutable position and request identity.

        Returns:
            Complete material/square facts for that exact context.

        Raises:
            ValueError: The input cannot be represented by this plugin.
        """
        ...

    def close(self) -> None:
        """Release resources after this worker's single request."""
        ...