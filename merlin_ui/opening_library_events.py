"""Desktop notifications after committed library edits; no chess or storage logic."""
from weakref import WeakSet
_views=WeakSet()


def register(view):_views.add(view)


def changed(root):
    for view in tuple(_views):
        if view.winfo_exists() and view.managed_root()==root:
            view.library_changed()


def unregister(view: object) -> None:
    """Remove a destroyed subscriber even while its controller remains referenced.

    Args:
        view: Previously registered desktop listener.
    """
    _views.discard(view)
