from __future__ import annotations

import argparse
from pathlib import Path


SKIP_DIRS = {
    ".git",
    ".venv",
    "Engines",
    "__pycache__",
}

TEXT_EXTENSIONS = {
    ".py",
    ".txt",
    ".md",
    ".json",
    ".toml",
    ".ini",
    ".cfg",
    ".yaml",
    ".yml",
}

REPLACEMENTS = (
    ("Chess Puzzle Wizard", "ChessWizard"),
    ("CHESS PUZZLE WIZARD", "CHESSWIZARD"),
    ("ChessPuzzleWizard", "ChessWizard"),
)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Safely rebrand project text from Chess Puzzle Wizard / "
            "ChessPuzzleWizard to ChessWizard."
        )
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write the changes. Without this flag, only preview them.",
    )

    return parser.parse_args()


def should_skip(path: Path) -> bool:
    return any(
        part in SKIP_DIRS
        for part in path.parts
    )


def main():
    args = parse_args()

    root = Path(__file__).resolve().parent

    changed = []
    replacement_count = 0

    script_path = Path(__file__).resolve()

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        if path.resolve() == script_path:
            continue

        relative = path.relative_to(root)

        if should_skip(relative):
            continue

        if path.suffix.lower() not in TEXT_EXTENSIONS:
            continue

        try:
            original = path.read_text(
                encoding="utf-8"
            )
        except UnicodeDecodeError:
            continue

        updated = original
        file_replacements = 0

        for old, new in REPLACEMENTS:
            count = updated.count(old)

            if count:
                updated = updated.replace(
                    old,
                    new,
                )

                file_replacements += count

        if updated == original:
            continue

        changed.append(
            (
                relative,
                file_replacements,
            )
        )

        replacement_count += file_replacements

        if args.apply:
            path.write_text(
                updated,
                encoding="utf-8",
            )

    print()
    print("CHESSWIZARD REBRAND")
    print("===================")

    if args.apply:
        print("Mode: APPLY")
    else:
        print("Mode: PREVIEW ONLY")

    print()

    if not changed:
        print("No old Chess Puzzle Wizard branding was found.")
        return 0

    for relative, count in changed:
        print(
            f"{relative}  ({count} replacement"
            f"{'' if count == 1 else 's'})"
        )

    print()
    print(
        f"Files affected: {len(changed):,}"
    )

    print(
        f"Text replacements: {replacement_count:,}"
    )

    if not args.apply:
        print()
        print(
            "Nothing was changed. "
            "Run this to apply the rebrand:"
        )

        print(
            "python rebrand_chesswizard.py --apply"
        )

    else:
        print()
        print(
            "Text rebrand complete."
        )

        print(
            "The project folder itself is NOT renamed by this script."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
