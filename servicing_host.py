"""Frozen installer helper: no UI, database access, plugin imports, or engine calls."""
import argparse
import json
from pathlib import Path
from servicing_inventory import load_inventory, verify_payload
from servicing_paths import tree_files, validate_roots
from servicing_profile import CONFIRMATION, removal_preview, remove_profile
from servicing_transaction import prepare, rollback, validate_and_prune


def main(argv: list[str] | None = None) -> int:
    """Run one explicit servicing action and write a bounded durable result.

    Args:
        argv: Optional command-line arguments.

    Returns:
        Zero on success; twenty for a refused/failed servicing action.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "validate", "rollback", "uninstall-check", "preview-removal", "remove-profile"))
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--transaction", type=Path)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--confirm")
    args = parser.parse_args(argv)
    try:
        validate_roots(args.app, args.profile, args.fixture)
        if args.action == "prepare":
            result = prepare(args.source, args.app, args.profile, args.transaction, args.fixture)
        elif args.action == "validate":
            result = validate_and_prune(args.transaction)
        elif args.action == "rollback":
            result = rollback(args.transaction)
        elif args.action == "uninstall-check":
            tree_files(args.app)
            result = {"safe": True, "profile_preserved": True}
        elif args.action == "preview-removal":
            result = removal_preview(args.app, args.profile, args.fixture)
        else:
            preview = json.loads(args.preview.read_text(encoding="utf-8"))['result']
            result = remove_profile(args.app, args.profile, preview['identity'], args.confirm, args.fixture)
        output, code = {"success": True, "action": args.action, "result": result}, 0
    except Exception as error:
        output, code = {"success": False, "action": args.action, "error": type(error).__name__, "message": str(error)}, 20
    args.receipt.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
