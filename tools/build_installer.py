"""Compile a pinned per-user installer from an exact, versioned owned payload."""
import argparse
import json
from pathlib import Path
import subprocess
from chesswizard_version import VERSION
from servicing_inventory import INVENTORY_NAME, file_hash, load_inventory, verify_payload
from servicing_paths import FIXTURE_MARKER, validate_roots

ROOT = Path(__file__).resolve().parents[1]


def build_installer(payload: Path, output: Path, fixture: Path | None = None) -> Path:
    """Validate and compile one consumer or explicitly isolated test installer.

    Args:
        payload: Exact frozen payload containing its ownership inventory.
        output: Local output directory; no publishing occurs.
        fixture: Optional marked temporary fixture root for disposable Windows tests.

    Returns:
        Compiled installer path.

    Raises:
        ValueError: Inventory, version, compiler, or disposable-root checks fail.
        RuntimeError: The pinned Inno compiler fails.
    """
    payload = payload.absolute()
    inventory = load_inventory(payload / INVENTORY_NAME)
    verify_payload(payload, inventory, exact=True)
    compiler = ROOT / "build/windows/installer-tools/inno-6.7.3/ISCC.exe"
    toolchain = json.loads((ROOT / "packaging/windows/installer-toolchain.json").read_text(encoding="utf-8"))
    if file_hash(compiler) != toolchain['compiler_sha256']:
        raise ValueError("Unreviewed Inno compiler bytes")
    arguments = [str(compiler), "/Qp", "/DAppVersion=" + inventory.version,
                 "/DPayloadDir=" + str(payload), "/DOutputPath=" + str(output.resolve())]
    if fixture is None:
        if inventory.version != VERSION:
            raise ValueError("Consumer installer must use the canonical application version")
    else:
        fixture = fixture.absolute()
        validate_roots(fixture / "app", fixture / "profile", fixture / FIXTURE_MARKER)
        import uuid
        arguments += ["/DFixtureRoot=" + str(fixture), "/DFixtureId=" + str(uuid.uuid5(uuid.UUID("67CE3406-96D1-4EB6-AF71-3C95D925CF8B"), str(fixture))).upper()]
    output.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([*arguments, str(ROOT / "packaging/windows/ChessWizard.iss")],
        capture_output=True, text=True, timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError("Inno compiler failed: " + result.stdout + result.stderr)
    return output / f"ChessWizard-{inventory.version}-Windows-x64-Setup.exe"


def main() -> int:
    """Compile only explicitly supplied, validated build inputs.

    Returns:
        Zero when the installer has been created.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixture", type=Path)
    args = parser.parse_args()
    print(build_installer(args.payload, args.output, args.fixture))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
