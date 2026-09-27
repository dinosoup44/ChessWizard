"""Generic package privacy boundaries with optional local, redacted deny rules."""
from dataclasses import dataclass
import json
from pathlib import Path, PurePosixPath
import re

PRIVATE_PARTS = frozenset({'tests', 'reports', 'reviews', 'review_data', 'backups',
    'backup', '.git', '.venv', '__pycache__', 'cache', 'caches', 'opening_books',
    'appdata', 'local_data', 'logs', 'screenshots'})
PUBLIC_BOOK = 'assets/openings/ChessWizard Default Openings.cwbook'
PRIVATE_SUFFIXES = frozenset({'.db', '.sqlite', '.sqlite3', '.jsonl', '.pgn', '.log',
    '.csv', '.bak', '.backup', '.tmp', '.trace', '.prof'})
CREDENTIAL = re.compile(r'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{35,}|sk-[A-Za-z0-9]{35,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')
HOME_PATH = re.compile(r'(?i)(?:[a-z]:[\\/]+users[\\/]+[^\\/\s\"\x00]+|/(?:home|Users)/[^/\s\"\x00]+)')


@dataclass(frozen=True)
class PrivacyPolicy:
    """Supply extra private identifiers from local configuration, never source literals.

    Args:
        private_literals: Exact case-insensitive substrings forbidden in content.
    """
    private_literals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.private_literals, tuple) or any(not isinstance(x, str) or not x.strip() for x in self.private_literals):
            raise ValueError('Private literals must be a tuple of nonempty strings')


def load_privacy_policy(path: Path | None = None) -> PrivacyPolicy:
    """Load optional local privacy identifiers without displaying their values.

    Args:
        path: Local JSON file containing only a private_literals string list.

    Returns:
        The additional rules; generic rules always apply independently.

    Raises:
        OSError: The requested file cannot be read.
        ValueError: The configuration has unknown fields or invalid values.
    """
    if path is None:
        return PrivacyPolicy()
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Invalid local privacy configuration') from None
    if not isinstance(data, dict) or set(data) != {'private_literals'} or not isinstance(data['private_literals'], list):
        raise ValueError('Invalid local privacy configuration')
    return PrivacyPolicy(tuple(data['private_literals']))


def validate_package_path(name: str, policy: PrivacyPolicy = PrivacyPolicy()) -> None:
    """Reject runtime/private paths and path escapes, with one exact public book exception.

    Args:
        name: Relative archive/package member, optionally beneath _internal.
        policy: Additional private identifiers, also forbidden in member names.

    Raises:
        ValueError: The name is absolute, escaping, private or an unapproved book.
    """
    if any(value.casefold() in name.casefold() for value in policy.private_literals):
        raise ValueError('Configured private identifier in package path')
    normalized = name.replace('\\', '/')
    parts = PurePosixPath(normalized).parts
    if not parts or normalized.startswith('/') or ':' in normalized or '..' in parts:
        raise ValueError('Unsafe package member path')
    relative = normalized.removeprefix('_internal/')
    lower = normalized.casefold()
    leaf = PurePosixPath(lower).name
    suffix = PurePosixPath(lower).suffix
    if suffix == '.cwbook' and relative != PUBLIC_BOOK:
        raise ValueError('Private opening library in package')
    if (set(p.casefold() for p in parts) & PRIVATE_PARTS or suffix in PRIVATE_SUFFIXES
        or re.search(r'\.(?:db|sqlite|sqlite3)(?:-(?:wal|shm|journal)|\.)',leaf)
        or leaf.endswith(('-wal','-shm','-journal','.activity-lock','.analysis-lock'))
        or leaf in {'settings.json','analysis_settings.json','occurrence_storage_lineage.json'}
        or leaf == '.env' or leaf.startswith('.env.') or leaf.endswith(('.key','.pem','.pfx','.p12','.credentials.json','.privacy.json'))):
        raise ValueError('Private runtime artifact in package')


def content_findings(data: bytes, policy: PrivacyPolicy = PrivacyPolicy()) -> tuple[str, ...]:
    """Return redacted categories for private paths, credentials and configured identifiers.

    Args:
        data: UTF-8, UTF-16 or binary package contents to inspect.
        policy: Optional additional private literals; no match values are returned.

    Returns:
        Sorted finding labels, without source snippets or private values.
    """
    found = set()
    for text in (data.decode('utf-8',errors='ignore'), data.decode('utf-16le',errors='ignore')):
        if HOME_PATH.search(text): found.add('user-home path')
        if CREDENTIAL.search(text): found.add('credential-like token')
        folded = text.casefold()
        if 'onedrive' in folded: found.add('personal sync location')
        if re.search(r'(?i)[a-z]:[\\/]+[^\r\n\"\x00]*(?:backups|backup)[\\/]',text): found.add('local backup path')
        if any(value.casefold() in folded for value in policy.private_literals): found.add('configured private literal')
    return tuple(sorted(found))
