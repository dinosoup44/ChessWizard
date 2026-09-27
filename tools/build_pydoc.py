"""Generate browsable API pages in build/pydoc; never edit source files."""
from pathlib import Path
import html
import sys
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.pydoc_support import ROOT, render_modules


def build_documentation() -> int:
    """Render all approved APIs before writing generated HTML and its index.

    Returns:
        Zero on success; one if any module failed, with no partial new output.

    Raises:
        OSError: The generated output directory cannot be written.
        ValueError: The output path redirects outside the checkout build directory.
    """
    results = render_modules()
    failures = [r for r in results if r.error]
    if failures:
        for result in failures:
            print(f"FAIL {result.name}: {result.error}", file=sys.stderr)
        return 1
    destination = ROOT / 'build/pydoc'
    if destination.resolve() != destination.absolute() or destination.is_symlink():
        raise ValueError('Documentation output must be a normal checkout build directory')
    destination.mkdir(parents=True, exist_ok=True)
    for result in results:
        page = destination / (result.name + '.html')
        if page.is_symlink():
            raise ValueError('Documentation page must not be a symlink')
    index = destination / 'index.html'
    if index.is_symlink():
        raise ValueError('Documentation index must not be a symlink')
    for result in results:
        (destination / (result.name + '.html')).write_text(result.html, encoding='utf-8')
    links = ''.join(f'<li><a href="{html.escape(r.name)}.html">{html.escape(r.name)}</a></li>\n' for r in results)
    index.write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>ChessWizard APIs</title>'
                     '<h1>ChessWizard reusable APIs</h1><ul>' + links + '</ul></html>\n', encoding='utf-8')
    print(f'Generated {len(results)} API pages and build/pydoc/index.html')
    return 0


def main() -> int:
    """Build documentation with concise error reporting.

    Returns:
        Nonzero if rendering or writing fails.
    """
    try:
        return build_documentation()
    except (RuntimeError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
