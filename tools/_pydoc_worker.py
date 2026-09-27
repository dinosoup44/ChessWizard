"""Isolated, side-effect-denying worker; invoked only by pydoc_support."""
import importlib
import json
import os
from pathlib import Path
import pydoc
import re
import sys


def _guard(event: str, args: tuple) -> None:
    """Deny runtime activity during trusted module documentation, not sandbox untrusted code."""
    if event in {"subprocess.Popen", "os.system", "os.posix_spawn", "sqlite3.connect"} or event.startswith("socket."):
        raise RuntimeError("Runtime activity forbidden while documenting modules")
    if event == "import" and (args[0] == "tkinter" or args[0].startswith("tkinter.")):
        raise RuntimeError("GUI imports forbidden in the reusable API index")
    if event == "open" and isinstance(args[2], int) and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
        raise RuntimeError("File writes forbidden while documenting modules")
    if event in {"os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.link", "os.symlink", "os.chmod"}:
        raise RuntimeError("Filesystem mutation forbidden while documenting modules")


def _clean(value: str, root: Path) -> str:
    """Remove machine paths and address-bearing default representations from generated pages."""
    value = re.sub(r'<a href="file:[^"]*">[^<]*</a>', 'source in checkout', value)
    value = value.replace(str(root), '<checkout>').replace(root.as_posix(), '<checkout>')
    value = re.sub(r' at 0x[0-9A-Fa-f]+', ' at <address>', value)
    return value


def main() -> None:
    """Render stdin module names and emit JSON results without importing entry points."""
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    names = json.loads(sys.stdin.read())
    sys.addaudithook(_guard)
    results = []
    for name in names:
        try:
            module = importlib.import_module(name)
            text = pydoc.render_doc(module, renderer=pydoc.plaintext)
            html = pydoc.HTMLDoc().page(name, pydoc.HTMLDoc().docmodule(module))
            results.append(dict(name=name, text=_clean(text, root), html=_clean(html, root), error=""))
        except Exception as error:
            results.append(dict(name=name, error=type(error).__name__ + ': import/render failed (runtime activity is forbidden)'))
    sys.stdout.write(json.dumps(results, ensure_ascii=True))


if __name__ == "__main__":
    main()
