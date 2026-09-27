"""Verified, latest-only recovery mirrors; never remove unowned directories."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import uuid

MARKER = 'CHESSWIZARD_RECOVERY.json'

def digest(path: Path) -> str:
    if path.stat().st_size == 0:
        return hashlib.sha256(b'').hexdigest()
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def manifest(root: Path) -> dict[str, str]:
    """Hash regular files and refuse links before any recursive operation."""
    root = Path(root)
    for ancestor in (root, *root.parents):
        if ancestor.is_symlink() or ancestor.is_junction():
            raise ValueError('Recovery paths cannot contain links')
    result = {}
    for base, folders, files in os.walk(root):
        for name in folders + files:
            path = Path(base) / name
            if path.is_symlink() or path.is_junction():
                raise ValueError('Recovery trees cannot contain links')
        for name in files:
            path = Path(base) / name
            result[path.relative_to(root).as_posix()] = digest(path)
    return result

def mirror_verified_backup(source: Path, mirror_root: Path, mode: str) -> dict:
    """Stage and verify before replacing this tool's own latest FULL/QUICK slot."""
    source, mirror_root = Path(source), Path(mirror_root)
    for path in (source, mirror_root):
        for ancestor in (path, *path.parents):
            if ancestor.is_symlink() or ancestor.is_junction():
                raise ValueError('Recovery paths cannot contain links')
    source = source.resolve()
    if mode not in ('FULL', 'QUICK'):
        raise ValueError('Unknown backup mode')
    if not mirror_root.exists():
        return {'status': 'unavailable', 'path': str(mirror_root)}
    mirror_root = mirror_root.resolve()
    if mirror_root == source or source in mirror_root.parents or mirror_root in source.parents:
        raise ValueError('Recovery mirror must be separate from the backup')
    receipt = json.loads((source / 'VERIFICATION.json').read_text(encoding='utf-8'))
    if receipt.get('status') != 'PASS' or receipt.get('backup_type') != mode:
        raise ValueError('Only a verified backup may be mirrored')
    name = 'ChessWizard_LATEST_' + ('FULL' if mode == 'FULL' else 'SNAPSHOT')
    target = mirror_root / name
    previous = mirror_root / (name + '.previous')
    if previous.exists():
        raise ValueError('Previous recovery copy needs inspection; no replacement attempted')
    if target.exists():
        marker = json.loads((target / MARKER).read_text(encoding='utf-8'))
        if marker != {'owner': 'ChessWizard backup_merlin', 'mode': mode}:
            raise ValueError('Unowned recovery directory')
        manifest(target)
    expected = manifest(source)
    index = source / 'FILE_HASHES.json'
    if receipt.get('file_manifest_sha256') != digest(index):
        raise ValueError('Backup verification manifest changed')
    verified = json.loads(index.read_text(encoding='utf-8'))
    actual = {k: v for k, v in expected.items() if k not in ('FILE_HASHES.json', 'VERIFICATION.json')}
    if actual != verified:
        raise ValueError('Backup changed after verification')
    required = sum((source / p).stat().st_size for p in expected)
    if shutil.disk_usage(mirror_root).free < required:
        raise OSError('Not enough space to stage recovery copy; existing copy preserved')
    stage = mirror_root / (name + '.staging-' + uuid.uuid4().hex)
    shutil.copytree(source, stage)
    if manifest(stage) != expected:
        raise ValueError('Recovery mirror hash mismatch; existing copy preserved')
    (stage / MARKER).write_text(json.dumps({'owner': 'ChessWizard backup_merlin', 'mode': mode}))
    if target.exists():
        target.rename(previous)
    try:
        stage.rename(target)
    except OSError:
        if previous.exists():
            previous.rename(target)
        raise
    if previous.exists():
        # Exact direct-child ownership and link checks precede recursive removal.
        assert previous.resolve().parent == mirror_root
        manifest(previous)
        shutil.rmtree(previous)
    return {'status': 'PASS', 'path': str(target), 'files': len(expected), 'bytes': required}
