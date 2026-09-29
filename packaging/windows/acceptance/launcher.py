"""Console-only frozen entry point for the portable acceptance kit."""
import argparse
from pathlib import Path
from tools.acceptance.console import run_wizard
from tools.acceptance.workflow import consumer_workflow


def main() -> int:
    """Start the explicit kit workflow; no source or Python install is required.

    Returns:
        Acceptance status exit code; never release authorization.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kit',type=Path,required=True)
    args=parser.parse_args()
    return run_wizard(args.kit.absolute(), consumer_workflow)


if __name__ == '__main__':
    raise SystemExit(main())
