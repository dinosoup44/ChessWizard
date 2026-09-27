"""Desktop error presentation around the shared first-run bootstrap service."""
import logging
from pathlib import Path
import tkinter as tk
from default_opening_install import seed_default_openings
from tkinter import messagebox
from application_paths import resolve_database_path
from database_bootstrap import BootstrapError, ensure_database
from chesswizard_version import DISPLAY_VERSION


def prepare_database(root: tk.Misc, explicit: str | Path | None = None) -> Path | None:
    """Prepare startup storage and seed editable books only for a new library profile.

    Args:
        root: Desktop parent for startup failure presentation.
        explicit: Optional explicitly selected game database path.

    Returns:
        Ready database path, or None after presenting a startup failure.
    """
    try:
        path = ensure_database(resolve_database_path(explicit)).path
        seed_default_openings()
        return path
    except (BootstrapError, OSError, ValueError) as error:
        logging.getLogger(__name__).exception("ChessWizard startup failed")
        messagebox.showerror(DISPLAY_VERSION + " - Startup failed", str(error), parent=root)
        root.destroy()
        return None
