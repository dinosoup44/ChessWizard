"""Shared database/review path selection, without creating directories or files."""
import os
from pathlib import Path
import sys

DATABASE_NAME = "merlin.db"


def application_data_directory() -> Path:
    """Writable user data, independent of the checkout or executable location."""
    override = os.environ.get("CHESSWIZARD_DATA_DIR")
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            raise ValueError("CHESSWIZARD_DATA_DIR must be an absolute directory")
        return path
    local = os.environ.get("LOCALAPPDATA")
    return Path(local) / "ChessWizard" if local else Path.home() / ".local" / "share" / "ChessWizard"


def application_root() -> Path:
    return Path(__file__).resolve().parent


def resolve_database_path(explicit=None, *, root=None, frozen=None) -> Path:
    """Prefer explicit/profile data; preserve an existing source-checkout database."""
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    user_database = application_data_directory() / DATABASE_NAME
    if os.environ.get("CHESSWIZARD_DATA_DIR") or user_database.exists():
        return user_database.resolve()
    source_root = Path(root) if root is not None else application_root()
    is_frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    legacy_database = source_root / DATABASE_NAME
    if not is_frozen and legacy_database.is_file():
        return legacy_database.resolve()
    return user_database.resolve()


def resolve_review_path(database_path=None) -> Path:
    """Reuse existing development notes only for their original database."""
    database = resolve_database_path(database_path)
    legacy_database = application_root() / DATABASE_NAME
    legacy_reviews = application_root() / "reviews" / "human_analyzer_review.jsonl"
    if (not getattr(sys, "frozen", False) and not os.environ.get("CHESSWIZARD_DATA_DIR")
            and database == legacy_database and legacy_reviews.is_file()):
        return legacy_reviews
    directory = application_data_directory() if database == legacy_database else database.parent
    return directory / "reviews" / "human_analyzer_review.jsonl"
