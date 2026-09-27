"""Bounded documentation rendering for the explicitly indexed reusable APIs."""
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import sys
from collections.abc import Sequence

ROOT = Path(__file__).resolve().parents[1]
INDEX = Path(__file__).with_name("public_api.json")


@dataclass(frozen=True)
class ModuleDocumentation:
    """Carry rendered API output or a redacted import failure.

    Args:
        name: Fully qualified module name.
        text: Plain pydoc output.
        html: Browsable pydoc output.
        error: Failure category; empty on success.
    """
    name: str
    text: str = ""
    html: str = ""
    error: str = ""


def public_modules() -> tuple[str, ...]:
    """Read the versioned public API index without importing application code.

    Returns:
        Unique module names in the documented subsystem order.

    Raises:
        ValueError: The index is malformed or contains duplicate modules.
        OSError: The index cannot be read.
    """
    groups = json.loads(INDEX.read_text(encoding="utf-8"))
    names = tuple(name for group in groups.values() for name in group)
    if len(names) != len(set(names)) or any(not all(p.isidentifier() for p in n.split('.')) for n in names):
        raise ValueError("Invalid public API index")
    return names


def render_modules(modules: Sequence[str] | None = None) -> tuple[ModuleDocumentation, ...]:
    """Render APIs in a guarded child process with no GUI, engine, network or writes.

    Args:
        modules: Explicit module names for validation; None uses the approved index.

    Returns:
        One documentation result per module in input order.

    Raises:
        RuntimeError: The renderer exits unexpectedly or exceeds its time limit.
    """
    names = tuple(modules) if modules is not None else public_modules()
    try:
        result = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "tools/_pydoc_worker.py")],
            input=json.dumps(names), text=True, encoding="utf-8", capture_output=True,
            cwd=ROOT, timeout=90, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode != 0:
            raise RuntimeError("Documentation worker failed; no documentation was generated")
        return tuple(ModuleDocumentation(**row) for row in json.loads(result.stdout))
    except (subprocess.TimeoutExpired, ValueError, OSError) as error:
        raise RuntimeError("Documentation worker unavailable or timed out") from error
