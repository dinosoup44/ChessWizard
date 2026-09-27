"""Full-backup integration for protected managed books, including removed copies."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from application_paths import application_data_directory
from theme_core.assets import reject_links


def backup_managed_books(destination, *, root=None):
    """Copy coherent SQLite snapshots; fail the backup if any protected file fails."""
    root=Path(root) if root is not None else application_data_directory()/'opening_books'
    root=root.absolute();reject_links(root)
    if not root.exists():return 0,0
    target=Path(destination)/'managed_opening_books';reject_links(target)
    if root==target.absolute() or root in target.absolute().parents:raise ValueError('Backup must be outside managed books.')
    target.mkdir(parents=True,exist_ok=False)
    records=[]
    paths=sorted(root.rglob('*.cwbook'))
    if (root/'catalog.sqlite').exists():paths.append(root/'catalog.sqlite')
    for path in paths:
        reject_links(path);relative=path.relative_to(root);copy=target/relative
        copy.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(path.absolute().as_uri()+'?mode=ro',uri=True)) as source:
            with closing(sqlite3.connect(copy)) as backup:
                source.backup(backup)
                if backup.execute('PRAGMA quick_check').fetchall()!=[('ok',)] or backup.execute('PRAGMA foreign_key_check').fetchall():
                    raise ValueError('Managed opening backup integrity failed.')
        records.append(dict(path=str(relative),sha256=hashlib.sha256(copy.read_bytes()).hexdigest(),bytes=copy.stat().st_size))
    (target/'BACKUP_INFO.json').write_text(json.dumps(dict(kind='protected managed opening books',files=records),indent=2),encoding='utf-8')
    return len(records),sum(r['bytes'] for r in records)
