from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


DEFAULT_BACKUP_ROOT = Path(__file__).resolve().parent.parent / "Merlin_Backups"
DATABASE_NAME = "merlin.db"

QUICK_EXCLUDED_DIRS = {
    ".venv",
    "Engines",
    "__pycache__",
}

ALWAYS_EXCLUDED_DIRS = {
    "__pycache__",
}

EXCLUDED_FILE_PATTERNS = {
    "*.pyc",
    "*.pyo",
    "*.db-wal",
    "*.db-shm",
}

QUICK_EXCLUDED_FILE_PATTERNS = {
    "merlin_before_*.db",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a timestamped ChessWizard/Merlin project backup. "
            "Quick mode is the default."
        )
    )

    parser.add_argument(
        "--full",
        action="store_true",
        help="Include .venv and Engines. Python cache files are still skipped.",
    )

    parser.add_argument(
        "--destination",
        type=Path,
        default=DEFAULT_BACKUP_ROOT,
        help="Backup root; defaults to Merlin_Backups beside the project.",
    )

    parser.add_argument(
        "--label",
        default="",
        help=(
            "Optional short label added to the backup folder name, "
            'for example: --label "before-rename"'
        ),
    )

    parser.add_argument('--mirror-root', type=Path, default=Path('D:/'),
                        help='Optional recovery drive; absent media does not block backup.')
    parser.add_argument('--no-mirror', action='store_true', help='Keep only the verified local backup.')
    parser.add_argument('--book', action='append', type=Path, default=[],
                        help='Also snapshot an owner-authored .cwbook outside managed storage.')
    return parser.parse_args()


def safe_name(value: str) -> str:
    value = value.strip()

    if not value:
        return ""

    allowed = []

    for character in value:
        if character.isalnum() or character in {"-", "_"}:
            allowed.append(character)

        elif character.isspace():
            allowed.append("-")

    return "".join(allowed).strip("-_")[:60]


def should_skip_directory(
    directory_name: str,
    full_backup: bool,
) -> bool:
    if directory_name in ALWAYS_EXCLUDED_DIRS:
        return True

    if (
        not full_backup
        and directory_name in QUICK_EXCLUDED_DIRS
    ):
        return True

    return False


def should_skip_file(
    file_name: str,
    full_backup: bool,
) -> bool:
    if file_name == DATABASE_NAME:
        # merlin.db is copied separately with SQLite's backup API.
        return True

    for pattern in EXCLUDED_FILE_PATTERNS:
        if fnmatch.fnmatch(file_name, pattern):
            return True

    if not full_backup:
        for pattern in QUICK_EXCLUDED_FILE_PATTERNS:
            if fnmatch.fnmatch(file_name, pattern):
                return True

    return False


def validate_backup_location(project_root: Path, destination: Path) -> None:
    """A backup must be outside its source, even when both share a drive."""
    source = project_root.resolve()
    target = destination.resolve()
    if target == source or source in target.parents:
        raise ValueError("Backup destination must be outside the active project")


def copy_project_files(
    project_root: Path,
    destination: Path,
    full_backup: bool,
) -> tuple[int, int]:
    validate_backup_location(project_root, destination)
    copied_files = 0
    copied_bytes = 0

    for current_root, directory_names, file_names in os.walk(project_root):
        current_path = Path(current_root)

        directory_names[:] = [
            name
            for name in directory_names
            if not should_skip_directory(name, full_backup)
        ]

        relative_root = current_path.relative_to(project_root)
        destination_root = destination / relative_root
        destination_root.mkdir(parents=True, exist_ok=True)

        for file_name in file_names:
            if should_skip_file(file_name, full_backup):
                continue

            source_file = current_path / file_name
            destination_file = destination_root / file_name

            shutil.copy2(
                source_file,
                destination_file,
            )

            copied_files += 1

            try:
                copied_bytes += source_file.stat().st_size

            except OSError:
                pass

    return copied_files, copied_bytes


def backup_database(
    source_database: Path,
    destination_database: Path,
) -> None:
    if not source_database.exists():
        raise FileNotFoundError(
            f"Database not found: {source_database}"
        )

    destination_database.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    source_connection = sqlite3.connect(str(source_database))
    destination_connection = sqlite3.connect(str(destination_database))

    try:
        source_connection.backup(destination_connection)
        destination_connection.commit()

    finally:
        destination_connection.close()
        source_connection.close()


def verify_database(database_path: Path) -> str:
    connection = sqlite3.connect(str(database_path))

    try:
        cursor = connection.cursor()
        cursor.execute("PRAGMA quick_check")
        row = cursor.fetchone()

        if row is None:
            return "No result"

        return str(row[0])

    finally:
        connection.close()


def human_size(byte_count: int) -> str:
    size = float(byte_count)
    units = ["B", "KB", "MB", "GB", "TB"]

    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size):,} {unit}"

            return f"{size:,.2f} {unit}"

        size /= 1024

    return f"{byte_count:,} B"


def write_backup_info(
    backup_directory: Path,
    project_root: Path,
    mode: str,
    copied_files: int,
    copied_bytes: int,
    database_size: int,
    database_check: str,
    started_at: datetime,
    finished_at: datetime,
) -> None:
    total_bytes = copied_bytes + database_size

    info = f"""ChessWizard / Merlin Backup
===========================

Backup mode: {mode}
Created: {finished_at.strftime("%Y-%m-%d %H:%M:%S")}
Source: {project_root}
Destination: {backup_directory}

Project files copied: {copied_files:,}
Project file bytes: {human_size(copied_bytes)}
Database: {DATABASE_NAME}
Database bytes: {human_size(database_size)}
SQLite quick_check: {database_check}

Total copied bytes: {human_size(total_bytes)}
Elapsed seconds: {(finished_at - started_at).total_seconds():.1f}

Quick mode exclusions:
- .venv
- Engines
- __pycache__
- *.pyc / *.pyo
- SQLite WAL/SHM sidecar files
- merlin_before_*.db

The live merlin.db was copied using SQLite's backup API rather than
a normal file copy, then the backup copy was verified with PRAGMA quick_check.
"""

    info_path = backup_directory / "BACKUP_INFO.txt"
    info_path.write_text(info, encoding="utf-8")


def main() -> int:
    """Create a local verified backup before updating optional removable recovery."""
    from contextlib import ExitStack
    from application_paths import application_data_directory
    from data_activity import exclusive_data_activity
    from backup_recovery import digest, manifest, mirror_verified_backup
    from backup_verification import database_state, snapshot_profile, verify_project, write_verification

    args = parse_args()
    started = datetime.now()
    project = Path(__file__).resolve().parent
    mode = 'FULL' if args.full else 'QUICK'
    label = safe_name(args.label)
    name = started.strftime('%Y-%m-%d_%H%M%S') + '_' + mode + '_ChessWizard'
    backup = args.destination.expanduser().resolve() / (name + ('_' + label if label else ''))
    profile = application_data_directory()
    try:
        validate_backup_location(project, backup)
        validate_backup_location(profile, backup)
        if backup.exists():
            raise ValueError('Backup destination already exists')
        # Reject links rather than following them into unrelated trees.
        manifest(project)
        sources = [project / DATABASE_NAME]
        if (profile / DATABASE_NAME).exists():
            sources.append(profile / DATABASE_NAME)
        with ExitStack() as locks:
            for path in sorted(set(p.resolve() for p in sources)):
                locks.enter_context(exclusive_data_activity(path))
            before = {str(p): digest(p) for p in sources}
            backup.mkdir(parents=True)
            print(f'Creating {mode}: {backup}', flush=True)
            count, size = copy_project_files(project, backup, args.full)
            backup_database(project / DATABASE_NAME, backup / DATABASE_NAME)
            profiles = snapshot_profile(profile, backup / 'desktop-profile')
            books = []
            for index, book in enumerate(args.book):
                book = book.expanduser().resolve()
                if book.suffix.lower() != '.cwbook':
                    raise ValueError('Owner book must be a .cwbook')
                target = backup / 'owner-books' / f'{index + 1:03d}' / book.name
                original = digest(book)
                backup_database(book, target)
                if database_state(book) != database_state(target) or digest(book) != original:
                    raise ValueError('Owner book changed during backup')
                books.append({'source': str(book), 'backup': str(target), 'source_sha256': original})
            print('Verifying project hashes and database contents...', flush=True)
            checks = verify_project(project, backup, args.full)
            if any(digest(Path(p)) != value for p, value in before.items()):
                raise ValueError('Source database changed during backup')
            write_backup_info(backup, project, mode, count, size,
                              (backup / DATABASE_NAME).stat().st_size, 'ok', started, datetime.now())
            write_verification(backup, mode, {**checks, 'profiles': profiles, 'owner_books': books})
        print(f'{mode} VERIFIED: {backup}', flush=True)
        if not args.no_mirror:
            result = mirror_verified_backup(backup, args.mirror_root, mode)
            print('Recovery mirror: ' + str(result), flush=True)
        return 0
    except Exception as error:
        print(f'BACKUP / RECOVERY FAILED: {error}\nInspect: {backup}', flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
