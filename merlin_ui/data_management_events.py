"""Coordinate desktop views of one database without putting deletion logic in widgets."""
from pathlib import Path
from weakref import WeakSet

_views = WeakSet()
_operations = WeakSet()


def register_operation(operation):
    _operations.add(operation)


def register(view):
    _views.add(view)


def _matching(path):
    for view in tuple(_views):
        if Path(view.database_path).resolve() == Path(path).resolve() and view.root.winfo_exists():
            yield view


def require_idle(path):
    for view in _matching(path):
        view.require_data_idle()


def changed(path):
    for view in _matching(path):
        view.refresh_after_data_change()


def operation_busy(path):
    return any(not item.closed and item.busy and Path(item.database_path).resolve() == Path(path).resolve()
               for item in tuple(_operations))
