"""Validate every indexed reusable API without launching ChessWizard."""
from pathlib import Path
import sys
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.pydoc_support import render_modules


def main() -> int:
    """Print documentation failures and return a process exit status.

    Returns:
        Zero when all indexed modules import and render; one otherwise.
    """
    try:
        results = render_modules()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    failures = [r for r in results if r.error]
    for result in failures:
        print(f"FAIL {result.name}: {result.error}", file=sys.stderr)
    print(f"pydoc: {len(results) - len(failures)}/{len(results)} modules rendered; {len(failures)} failures")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
