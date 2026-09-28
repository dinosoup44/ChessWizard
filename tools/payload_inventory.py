"""Build/verify explicit application ownership without touching installed profiles."""
import argparse
import json
from pathlib import Path
from chesswizard_version import VERSION
from servicing_inventory import create_inventory, load_inventory, verify_payload, INVENTORY_NAME


def main() -> int:
    """Create or verify the exact frozen payload inventory.

    Returns:
        Zero after successful ownership validation.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--synthetic-version", help="Explicit test-build version; never changes the application release")
    args = parser.parse_args()
    args.payload = args.payload.absolute()
    if args.verify:
        inventory = load_inventory(args.payload / INVENTORY_NAME)
        verify_payload(args.payload, inventory, exact=True)
    else:
        inventory = create_inventory(args.payload, args.synthetic_version or VERSION)
    print(json.dumps({"version": inventory.version, "files": len(inventory.files), "bytes": sum(f.size for f in inventory.files)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
