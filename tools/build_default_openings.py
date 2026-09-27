"""Build the pinned default library into an explicitly new directory."""
import argparse
from pathlib import Path
from default_opening_builder import generate_library


def main() -> None:
    """Parse offline build paths and print a compact verified content receipt."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('data/default_openings/source'))
    parser.add_argument('--curation', type=Path, default=Path('data/default_openings/curation.json'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = generate_library(args.source, args.curation, args.output)
    print({key:result[key] for key in ('families','variations','positions','entry_positions','selected_rows','cwbook_bytes','polyglot')})


if __name__ == '__main__':
    main()
