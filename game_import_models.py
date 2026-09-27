"""Frontend-independent import progress and completed-result contracts."""
from dataclasses import dataclass

SOURCE_LABELS = {"chesscom": "Chess.com", "lichess": "Lichess"}


@dataclass(frozen=True)
class ImportProgress:
    """Expose received, added, duplicate, ignored, error and empty-record counts.

    Args:
        message: Current import activity.
        found: Records received.
        added: Committed games.
        existing: Duplicate identities.
        errors: Invalid records/download failures.
        ignored: User-suppressed games.
        skipped_empty: Records with zero legal registered moves.
    """
    message: str
    found: int = 0
    added: int = 0
    existing: int = 0
    errors: int = 0
    ignored: int = 0
    skipped_empty: int = 0


@dataclass(frozen=True)
class ImportResult:
    """Summarize import dispositions without starting analysis.

    Args:
        source: Canonical provider name.
        username: Requested account.
        found: Records received.
        added: Games committed.
        existing: Duplicate identities.
        errors: Invalid records/download failures.
        details: Error explanations.
        cancelled: Whether the caller stopped importing.
        ignored: User-suppressed games.
        skipped_empty: Zero-legal-move records skipped before insertion.
    """
    source: str
    username: str
    found: int = 0
    added: int = 0
    existing: int = 0
    errors: int = 0
    details: tuple[str, ...] = ()
    cancelled: bool = False
    ignored: int = 0
    skipped_empty: int = 0

    def summary(self) -> str:
        """Format every import disposition separately.

        Returns:
            User-facing summary including skipped empty games.
        """
        title = "Import stopped" if self.cancelled else "Import finished with errors" if self.errors else "Import complete"
        return (f"{title}\nAccount: {self.username}\nSource: {SOURCE_LABELS.get(self.source, self.source)}\n\n"
                f"Games received: {self.found:,}\nNew games added: {self.added:,}\n"
                f"Already imported: {self.existing:,}\nIgnored by user: {self.ignored:,}\n"
                f"Skipped empty/zero-move games: {self.skipped_empty:,}\nErrors: {self.errors:,}\n\n"
                "Analysis has not been run.\n" + "\n".join(self.details))
