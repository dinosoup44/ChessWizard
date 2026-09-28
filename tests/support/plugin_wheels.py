"""Reusable synthetic wheels; no private source, owner games, or installed artifacts."""
import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile
import chess

PLUGIN_ID = "org.example.inventory"
PACKAGE = "chesswizard_plugin_test"
FEN = chess.STARTING_FEN
GOOD_CODE = '''
from chesswizard_plugin_api import MaterialFacts, SquareFact, MaterialCount
class Plugin:
    def analyze(self, context):
        names = dict(zip("pnbrqk", ("pawn","knight","bishop","rook","queen","king")))
        squares = []
        for row, rank in enumerate(context.fen.split()[0].split("/")):
            file = 0
            for token in rank:
                if token.isdigit():
                    file += int(token)
                else:
                    squares.append(SquareFact(chr(97+file)+str(8-row),
                        "white" if token.isupper() else "black", names[token.lower()]))
                    file += 1
        counts = tuple(MaterialCount(color, piece, sum(f.color==color and f.piece==piece for f in squares))
            for color in ("white","black") for piece in names.values())
        return MaterialFacts(context.request_id, context.fen, tuple(squares), counts)
    def close(self):
        pass
def create_plugin():
    return Plugin()
'''


def make_wheel(directory: Path, *, code: str = GOOD_CODE, api: str = "1.0.0",
               minimum: str = "1.0.0b0", extra: dict[str, bytes] | None = None, plugin_id: str = PLUGIN_ID,
               omit: tuple[str, ...] = ()) -> Path:
    """Build synthetic standard wheel metadata for contract tests.

    Args:
        directory: Temporary output directory.
        code: Synthetic plugin module.
        api: Required API version.
        minimum: Minimum application version.
        extra: Optional archive entries used by rejection tests.
        plugin_id: Synthetic stable identity.
        omit: Entries intentionally missing in invalid fixture tests.

    Returns:
        Local test wheel path.
    """
    info = "chesswizard_plugin_test-1.0.0.dist-info"
    manifest = dict(schema_version=1, plugin_id=plugin_id, display_name="Synthetic inventory",
                    minimum_app_version=minimum, api_version=api, type="position_facts",
                    capabilities=["material_inventory"])
    files = {
        PACKAGE + "/__init__.py": code.encode(),
        PACKAGE + "/chesswizard-plugin.json": json.dumps(manifest).encode(),
        info + "/METADATA": b"Metadata-Version: 2.4\nName: chesswizard-plugin-test\nVersion: 1.0.0\nAuthor: Test contributors\nLicense-Expression: GPL-3.0-or-later\nRequires-Python: >=3.14,<3.15\nRequires-Dist: chesswizard-plugin-api>=1.0,<2\n",
        info + "/WHEEL": b"Wheel-Version: 1.0\nGenerator: synthetic-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        info + "/entry_points.txt": f"[chesswizard.plugins]\n{plugin_id} = {PACKAGE}:create_plugin\n".encode(),
    }
    files.update(extra or {})
    for name in omit:
        files.pop(name, None)
    record = io.StringIO(newline="")
    writer = csv.writer(record)
    for name, data in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        writer.writerow((name, "sha256=" + digest, len(data)))
    writer.writerow((info + "/RECORD", "", ""))
    files[info + "/RECORD"] = record.getvalue().encode()
    path = directory / "chesswizard_plugin_test-1.0.0-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0)), data)
    return path

