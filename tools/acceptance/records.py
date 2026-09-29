"""Durable acceptance observations; interrupted work never defaults to PASS."""
from __future__ import annotations
from collections.abc import Callable
import hashlib
import json
import os
from pathlib import Path
import stat
from datetime import datetime, timezone
from uuid import uuid4
from tools.release_acceptance import FINAL_PLAN, receipt_template


def checked_path(root: Path, relative: str) -> Path:
    """Resolve a kit member without following links.

    Args:
        root: Explicit kit directory.
        relative: Forward-slash relative member name.

    Returns:
        Contained absolute path.

    Raises:
        ValueError: Absolute, traversal or reparse paths are encountered.
    """
    if not relative or relative.startswith('/') or ':' in relative or '\\' in relative or Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('Unsafe kit path')
    target = root / relative
    ancestors = (root, *root.parents, *[root.joinpath(*Path(relative).parts[:n]) for n in range(1, len(Path(relative).parts)+1)])
    for part in ancestors:
        if part.is_symlink() or (part.exists() and getattr(part.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise ValueError('Linked directory/file is not allowed: '+str(part))
    return target


def atomic_text(path: Path, text: str) -> None:
    """Publish complete text while retaining previous bytes on failure.

    Args:
        path: Validated destination.
        text: UTF-8 content.

    Raises:
        OSError: Results cannot be persisted; stop before another operation.
    """
    temporary = path.with_name(path.name+'.'+uuid4().hex+'.tmp')
    try:
        with temporary.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


class RunRecord:
    """Persist a timestamped run before any test or installer operation.

    Args:
        kit: Writable portable kit directory.
        scope: clean_windows or simulation; simulations never certify release.
    """

    def __init__(self, kit: Path, scope: str = 'clean_windows') -> None:
        """Create an INCOMPLETE receipt and latest-result pointer.

        Args:
            kit: Explicit writable kit root.
            scope: Evidence provenance retained through all outcomes.

        Raises:
            OSError: Results cannot be persisted.
            ValueError: Kit paths or scope are unsafe.
        """
        if scope not in {'clean_windows', 'simulation'}:
            raise ValueError('Invalid evidence scope')
        self.kit = kit.absolute()
        self.folder = checked_path(self.kit, 'receipts')
        self.folder.mkdir(exist_ok=True)
        self.run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]
        self.path = checked_path(self.kit, 'receipts/acceptance-'+self.run_id+'.json')
        self.log = checked_path(self.kit, 'receipts/acceptance-'+self.run_id+'.log')
        self.data = receipt_template(FINAL_PLAN)
        self.data.update(status='INCOMPLETE', scope=scope, run_id=self.run_id, runner_pid=os.getpid(),
                         started_utc=datetime.now(timezone.utc).isoformat(), current_step='Start screen',
                         answers=[], release_approved=False)
        self.save()

    def save(self) -> None:
        """Checkpoint both the machine receipt and human-readable result."""
        self.data['updated_utc'] = datetime.now(timezone.utc).isoformat()
        atomic_text(self.path, json.dumps(self.data, indent=2)+'\n')
        atomic_text(checked_path(self.kit, 'receipts/latest.json'),
                    json.dumps({'receipt': self.path.relative_to(self.kit).as_posix()})+'\n')
        status = self.data['status']
        action = ('Send receipt/logs to the owner. Release approval is still separate.' if status == 'PASS'
                  else 'Do not continue release approval. Reopen START-HERE.cmd to review. Restore a clean test machine before restarting after installation.')
        atomic_text(checked_path(self.kit, 'VIEW-RESULT.txt'),
                    f"{status}\nDate/time (UTC): {self.data['updated_utc']}\nStep: {self.data['current_step']}\n"
                    f"Receipt: {self.path}\nLog: {self.log}\nNext action: {action}\n")

    def event(self, message: str) -> None:
        """Retain displayed progress in the run log.

        Args:
            message: Plain text shown to the tester.

        Raises:
            OSError: The log cannot be written.
        """
        with self.log.open('a', encoding='utf-8') as stream:
            stream.write(message+'\n')
            stream.flush()


def previous_result(kit: Path) -> dict | None:
    """Read the previous receipt through a contained, bounded pointer.

    Args:
        kit: Portable kit root.

    Returns:
        Prior receipt, or None for a first launch.

    Raises:
        ValueError: Prior evidence is malformed or unsafe.
        OSError: Existing evidence cannot be read.
    """
    pointer = checked_path(kit, 'receipts/latest.json')
    if not pointer.exists():
        return None
    if pointer.stat().st_size > 4096:
        raise ValueError('Invalid prior-result pointer')
    path = checked_path(kit, json.loads(pointer.read_text(encoding='utf-8-sig'))['receipt'])
    if path.stat().st_size > 2_000_000:
        raise ValueError('Prior receipt exceeds limit')
    result = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(result, dict):
        raise ValueError('Prior receipt must be an object')
    return result


def digest(path: Path, pulse: Callable[[], None] = lambda: None) -> str:
    """Hash incrementally while allowing visible progress.

    Args:
        path: Explicit input file.
        pulse: Progress callback; never starts background work.

    Returns:
        Lowercase SHA256 digest.
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024*1024):
            result.update(chunk)
            pulse()
    return result.hexdigest()
