"""Verification and user-profile snapshots for the approved backup workflow."""
from contextlib import closing
from pathlib import Path
import hashlib
import json
import os
import shutil
import sqlite3
from backup_recovery import digest, manifest

SQLITE_SUFFIXES = {'.db', '.sqlite', '.sqlite3', '.cwbook'}

def database_state(path: Path) -> dict:
    """Compare logical contents; SQLite backup may legitimately change file bytes."""
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        quick = db.execute('PRAGMA quick_check').fetchall()
        foreign = db.execute('PRAGMA foreign_key_check').fetchall()
        if quick != [('ok',)] or foreign:
            raise ValueError('Database integrity verification failed: ' + str(path))
        schema = db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        tables = {}
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            identifier = '"' + name.replace('"', '""') + '"'
            columns = db.execute('PRAGMA table_info(' + identifier + ')').fetchall()
            order = ','.join(str(i + 1) for i in range(len(columns)))
            rows = db.execute('SELECT * FROM ' + identifier + ' ORDER BY ' + order)
            h = hashlib.sha256(); count = 0
            for row in rows:
                h.update(repr(row).encode('utf-8')); count += 1
            tables[name] = {'rows': count, 'sha256': h.hexdigest()}
        return {'schema': schema, 'tables': tables, 'quick_check': 'ok', 'foreign_key_check': []}

def snapshot_profile(profile: Path, destination: Path) -> list[dict]:
    """Include settings, themes, reviews and coherent database/book snapshots."""
    import backup_merlin as workflow
    if not profile.exists():
        return []
    manifest(profile)  # Refuse links before traversing user data.
    records = []
    for base, folders, files in os.walk(profile):
        folders[:] = [n for n in folders if n != '__pycache__']
        for name in files:
            if name.endswith(('-wal', '-shm', '-journal', '.activity-lock', '.pyc', '.pyo')):
                continue
            source = Path(base) / name
            target = destination / source.relative_to(profile)
            target.parent.mkdir(parents=True, exist_ok=True)
            before = digest(source)
            if source.suffix.lower() in SQLITE_SUFFIXES:
                workflow.backup_database(source, target)
                if database_state(source) != database_state(target):
                    raise ValueError('Profile database differs: ' + str(source))
            else:
                shutil.copy2(source, target)
                if digest(target) != before:
                    raise ValueError('Profile copy mismatch: ' + str(source))
            if digest(source) != before:
                raise ValueError('User data changed during backup: ' + str(source))
            records.append({'source': str(source), 'backup': str(target), 'source_sha256': before, 'backup_sha256': digest(target)})
    return records

def verify_project(project: Path, backup: Path, full: bool) -> dict:
    """Verify every included project file plus the logical database snapshot."""
    import backup_merlin as workflow
    count = 0
    for base, folders, files in os.walk(project):
        folders[:] = [n for n in folders if not workflow.should_skip_directory(n, full)]
        for name in files:
            if workflow.should_skip_file(name, full):
                continue
            source = Path(base) / name; target = backup / source.relative_to(project)
            if not target.is_file() or digest(source) != digest(target):
                raise ValueError('Project hash mismatch: ' + str(source))
            count += 1
    source = project / workflow.DATABASE_NAME; target = backup / workflow.DATABASE_NAME
    if database_state(source) != database_state(target):
        raise ValueError('Project database logical mismatch')
    return {'project_files': count, 'production_db_sha256': digest(source), 'backup_db_sha256': digest(target), 'quick_check': 'ok', 'foreign_key_check': []}

def write_verification(backup: Path, mode: str, details: dict) -> dict:
    """Bind the PASS receipt to exact backup contents for recovery copying."""
    hashes = manifest(backup)
    index = backup / 'FILE_HASHES.json'
    index.write_text(json.dumps(hashes, indent=2), encoding='utf-8')
    receipt = {'status': 'PASS', 'backup_type': mode, 'file_manifest_sha256': digest(index), **details}
    (backup / 'VERIFICATION.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    return receipt
