"""Preview a public source manifest using real Git ignore semantics; never stage or publish."""
import argparse
from collections.abc import Sequence
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PRUNED = frozenset({'.git', '.venv', 'venv', '__pycache__', 'build', 'dist', 'backups',
    'reports', 'Engines', 'reviews', 'review_data', '.idea', '.vscode', '.pytest_cache'})
TEXT_SUFFIXES = {'.py', '.md', '.txt', '.json', '.jsonl', '.ps1', '.spec', '.iss', '.toml', '.yml', '.yaml', '.tsv'}
REVIEW_FILES: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Finding:
    """Describe a scan finding without copying a potentially sensitive value.

    Args:
        path: Checkout-relative file path.
        line: One-based source line.
        category: Review classification.
        reason: Pattern category, never the matched value.
    """
    path: str
    line: int
    category: str
    reason: str


def checkout_files(root: Path) -> tuple[Path, ...]:
    """List inspectable files while pruning known local/generated directories.

    Args:
        root: Source checkout to inspect.

    Returns:
        Sorted relative paths, including ignored files outside pruned directories.

    Raises:
        OSError: Source traversal fails; never silently certify an unreadable subtree.
        ValueError: A symlink is encountered in the proposed source tree.
    """
    paths = []
    def fail(error: OSError) -> None:
        raise error
    for folder, dirs, files in os.walk(root, followlinks=False, onerror=fail):
        dirs[:] = sorted(d for d in dirs if d not in PRUNED)
        for name in [*dirs, *files]:
            p = Path(folder) / name
            if p.is_symlink():
                raise ValueError('Review symlink before publication: ' + p.relative_to(root).as_posix())
        paths.extend((Path(folder) / name).relative_to(root) for name in files)
    return tuple(sorted(paths))


def ignored_paths(root: Path, paths: Sequence[Path]) -> frozenset[str]:
    """Evaluate the root .gitignore in a disposable Git repository with clean config.

    Args:
        root: Checkout supplying only its .gitignore contents.
        paths: Relative file names to test; no source file is copied or staged.

    Returns:
        Paths ignored by Git, as POSIX strings.

    Raises:
        RuntimeError: Git is unavailable or ignore validation fails.
        ValueError: A supplied path escapes the checkout.
    """
    names = [p.as_posix() for p in paths]
    if any(p.is_absolute() or '..' in p.parts for p in paths):
        raise ValueError('Ignore validation requires checkout-relative paths')
    if not names:
        return frozenset()
    git = shutil.which('git')
    if git is None:
        raise RuntimeError('Install Git to verify public ignore rules')
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    with tempfile.TemporaryDirectory(prefix='chesswizard-ignore-') as tmp:
        work = Path(tmp)
        shutil.copyfile(root / '.gitignore', work / '.gitignore')
        flags = dict(cwd=work, env=env, capture_output=True,
                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        init = subprocess.run([git, 'init', '--quiet', '--template=', '--initial-branch=main'], timeout=15, **flags)
        if init.returncode:
            raise RuntimeError('Disposable Git validation initialization failed')
        result = subprocess.run([git, '-c', 'core.excludesFile=' + os.devnull,
            'check-ignore', '--no-index', '-z', '--stdin'],
            input=('\0'.join(names) + '\0').encode('utf-8'), timeout=30, **flags)
        if result.returncode not in (0, 1):
            raise RuntimeError('Git ignore validation failed')
        return frozenset(result.stdout.decode('utf-8').strip('\0').split('\0')) if result.stdout else frozenset()


def scan_text(path: str, text: str) -> tuple[Finding, ...]:
    """Classify privacy/security patterns and report locations without matched values.

    Args:
        path: Public candidate's relative name.
        text: Decoded source/configuration contents.

    Returns:
        Findings needing contextual review, including explicitly safe keyword uses.
    """
    patterns = (
        ('potential secret', 'credential format', r'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{35,}|sk-[A-Za-z0-9]{35,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)'),
        ('local path to clean', 'user-home path', r'(?i)[A-Z]:[\\/]+Users[\\/]+[^\\/\s]+'),
        ('requires owner decision', 'private network address', r'\b(?:192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)\b'),
        ('safe/example', 'security or state keyword', r'(?i)\b(?:password|passwd|token|secret|api_key|authorization|bearer|connection_string)\b'),
        ('public-safe reference' if path.startswith('licenses/') else 'requires owner decision', 'email address', r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}'),
    )
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        for category, reason, pattern in patterns:
            matches = re.findall(pattern, line)
            if matches:
                effective = category
                if reason == 'email address' and path.endswith('.iss') and re.fullmatch(r"\s*external '[A-Za-z_]\w*@(?:kernel32|user32)\.dll stdcall';\s*", line):
                    effective = 'public-safe reference'
                if reason == 'email address' and not path.startswith('licenses/') and all(re.fullmatch(r'[\w.+-]+@example\.(?:org|com|net)', value) for value in matches):
                    effective = 'safe/example'
                found.append(Finding(path, number, effective, reason))
    return tuple(found)


def source_manifest(root: Path) -> dict:
    """Describe visible public candidates and review holds without altering the checkout.

    Args:
        root: Existing source checkout.

    Returns:
        File hashes, ignored paths and redacted scan findings; not release approval.

    Raises:
        OSError: A source file cannot be inspected.
        RuntimeError: Git ignore validation is unavailable.
        ValueError: A symlink or escaping input is found.
    """
    root = root.resolve()
    paths = checkout_files(root)
    ignored = ignored_paths(root, paths)
    files, findings = [], []
    for path in paths:
        name = path.as_posix()
        if name in ignored:
            continue
        raw = (root / path).read_bytes()
        files.append(dict(path=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
        if path.suffix.lower() in TEXT_SUFFIXES or name in {'.gitignore', '.gitattributes', 'LICENSE'}:
            findings.extend(scan_text(name, raw.decode('utf-8-sig')))
        if name in REVIEW_FILES:
            findings.append(Finding(name, 1, 'requires owner decision', 'historical packager embeds private denylist literals; replace safely before publishing'))
    return dict(schema_version=1, files=files, ignored=sorted(ignored),
                pruned_directory_names=sorted(PRUNED), findings=[asdict(f) for f in findings])


def main() -> int:
    """Write a local manifest preview and return nonzero for unresolved findings.

    Returns:
        Zero for no blocking pattern findings; one for review holds or tool failure.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        report = source_manifest(ROOT)
        output = ROOT / 'build/public-source-manifest.json'
        if output.resolve() != output.absolute() or output.is_symlink():
            raise ValueError('Manifest output must remain in the checkout build directory')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        blocking = [f for f in report['findings'] if f['category'] not in {'safe/example', 'public-safe reference'}]
        print(f"Public candidates: {len(report['files'])}; scan review holds: {len(blocking)}")
        print('Preview: build/public-source-manifest.json. This is not publication approval.')
        return int(bool(blocking))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print('Public source check failed: ' + type(error).__name__)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
