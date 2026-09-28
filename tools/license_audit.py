"""Read-only checks of human-reviewed license and proposed release inputs; no build."""
import argparse
import ast
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path, PurePosixPath
import sys

PROJECT = Path(__file__).resolve().parents[1]
PRIVATE_PARTS = {'.venv', '.git', 'reports', 'reviews', 'review_data', '__pycache__'}


def safe_file(root: Path, relative: str) -> Path:
    """Manifest paths cannot escape an input root, including through symlinks."""
    name = PurePosixPath(relative.replace('\\', '/'))
    if name.is_absolute() or '..' in name.parts or ':' in relative:
        raise ValueError('Unsafe manifest path: ' + relative)
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Manifest path escapes its root: ' + relative)
    return path


def check_hashes(entries, roots):
    errors = []
    for entry in entries:
        try:
            path = safe_file(roots[entry['root']], entry['path'])
            with path.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != entry['sha256']:
                errors.append('Changed input: ' + entry['path'])
        except (KeyError, OSError, ValueError) as error:
            errors.append('Input unavailable: ' + entry.get('path', '?') + ': ' + str(error))
    return errors


def external_imports(root: Path, entry_points: list[str] | tuple[str, ...]) -> set[str]:
    """Walk application and SDK source imports without executing modules.

    Args:
        root: Source tree containing the reviewed runtime entry points.
        entry_points: Local entry module names to trace.

    Returns:
        Non-standard-library top-level imports needing package review.
    """
    modules = {p.stem:p for p in root.glob('*.py')}
    for directory in ('merlin_ui', 'theme_core', 'feedback', 'board_analysis', 'position_range_evidence', 'chesswizard_plugin_api'):
        for path in (root/directory).rglob('*.py'):
            name = '.'.join(path.relative_to(root).with_suffix('').parts)
            modules[name.removesuffix('.__init__')] = path
    pending, seen, external = list(entry_points), set(), set()
    while pending:
        module = pending.pop()
        if module in seen or module not in modules:
            continue
        seen.add(module)
        path = modules[module]
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    parent = module.split('.') if path.name == '__init__.py' else module.split('.')[:-1]
                    parent = parent[:len(parent)-node.level+1]
                    stem = '.'.join(parent + ([node.module] if node.module else []))
                else:
                    stem = node.module or ''
                names = [stem] + [stem+'.'+alias.name for alias in node.names]
            for name in names:
                parts = name.split('.')
                local = ['.'.join(parts[:i]) for i in range(1,len(parts)+1)
                         if '.'.join(parts[:i]) in modules]
                if local:
                    pending.extend(local)
                elif parts[0] and parts[0] not in sys.stdlib_module_names:
                    external.add(parts[0])
    return external


def check_release_files(entries, root):
    errors = []
    for entry in entries:
        name = PurePosixPath(entry['path'])
        if set(name.parts) & PRIVATE_PARTS or name.suffix.lower() in {'.db', '.sqlite', '.jsonl', '.pgn'}:
            errors.append('Private/data file in release notices: ' + str(name))
    return errors + check_hashes(entries, {'project':root})


def audit(root=PROJECT):
    """Detect input drift; a clean input audit never clears unresolved release gates."""
    manifest = json.loads((root/'source_info/runtime_inputs.json').read_text(encoding='utf-8'))
    included = json.loads((root/'licenses/release_files.json').read_text(encoding='utf-8'))
    roots = {'project':root, 'python_base':Path(sys.base_prefix),
             'site_packages':Path(metadata.distribution('chess').locate_file(''))}
    errors = check_hashes(manifest['source_inputs']+manifest['candidate_runtime_inputs'], roots)
    errors += check_release_files(included, root)
    observed = external_imports(root, manifest['entry_points'])
    expected = set(manifest['expected_external_imports'])
    if observed != expected:
        errors.append('Runtime dependency imports changed: ' + repr(sorted(observed ^ expected)))
    for package in manifest['packages']:
        if package['classification'] != 'runtime':
            continue
        if not package.get('license') or package['license'].lower() in {'unknown', 'none'}:
            errors.append('Unreviewed runtime license: ' + package['name'])
        if metadata.version(package['name']) != package['version']:
            errors.append('Runtime package version changed: ' + package['name'])
    version_source = ast.parse((root/'chesswizard_version.py').read_text(encoding='utf-8-sig'))
    versions = [node.value.value for node in version_source.body if isinstance(node,ast.Assign)
                and any(isinstance(target,ast.Name) and target.id=='VERSION' for target in node.targets)]
    if versions != [manifest['release_version']]:
        errors.append('Release version mismatch')
    return {'errors':errors, 'release_gates':manifest['release_gates'],
            'status':'INPUT_ERRORS' if errors else 'INPUTS_MATCH_RELEASE_BLOCKED' if manifest['release_gates'] else 'INPUTS_MATCH',
            'application_sources_checked':len(manifest['source_inputs']),
            'candidate_runtime_files_checked':len(manifest['candidate_runtime_inputs']),
            'release_notice_files_checked':len(included), 'external_imports':sorted(observed),
            'package_built_or_certified':False}



def audit_package(distribution, manifest, root=PROJECT):
    """Close input licensing against every actual file; reject extra/missing/drifted files."""
    result = audit(root)
    errors = list(result["errors"])
    entries = manifest["files"]
    actual = {p.relative_to(distribution).as_posix() for p in distribution.rglob("*") if p.is_file()}
    declared = {e["path"] for e in entries}
    if actual != declared or len(declared) != len(entries):
        errors.append("Collected-file manifest mismatch or duplicate")
    errors += check_hashes([dict(e, root="package") for e in entries], {"package":distribution})
    for entry in entries + manifest["embedded_python_modules"] + manifest["boot_scripts"]:
        if not entry.get("owner") or not entry.get("license") or "unknown" in entry["license"].lower():
            errors.append("Unexplained shipped component")
    if manifest["privacy_findings"]:
        errors.append("Unresolved privacy finding")
    required = [e for e in json.loads((root/"licenses/release_files.json").read_text())
                if e["path"] not in {"source_info/runtime_inputs.json", "licenses/provenance.json"}]
    for entry in required:
        target = "_internal/" + entry["path"]
        if target not in declared:
            errors.append("Missing required notice/source pointer: " + target)
        else:
            errors += check_hashes([dict(entry,root="package",path=target)],{"package":distribution})
    if sum(e["owner"]=="Stockfish 18 AVX2" for e in entries) != 1:
        errors.append("Expected exactly one Stockfish executable")
    return dict(errors=errors, release_gates=[] if not errors else ["Actual package audit failed"],
        status="PACKAGING_INPUT_LICENSING_BLOCKER_RESOLVED" if not errors else "PACKAGE_ERRORS",
        package_built_or_certified=not errors, files_checked=len(entries),
        modules_checked=len(manifest["embedded_python_modules"]),
        external_distribution_authorized=False, manual_visual_qa_required=True)


def main() -> int:
    """Validate source inputs or an explicitly supplied frozen package.

    Returns:
        Zero when the requested audit has no errors or unresolved release gates.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',action='store_true',help='Fail on unresolved release gates as well as changed inputs')
    parser.add_argument("--package-dir", type=Path, help="Validate an actual frozen folder against reports/v1_package_manifest.json")
    parser.add_argument('--manifest', type=Path, help='Exact frozen manifest for --package-dir')
    args = parser.parse_args()
    try:
        result = (audit_package(args.package_dir, json.loads((args.manifest or PROJECT/"reports/v1_package_manifest.json").read_text()))
                  if args.package_dir else audit())
    except (OSError,ValueError,KeyError,metadata.PackageNotFoundError) as error:
        result = {'errors':[str(error)], 'release_gates':[], 'status':'AUDIT_FAILED'}
    print(json.dumps(result,indent=2))
    return int(bool(result['errors'] or (args.release and result['release_gates'])))


if __name__ == '__main__':
    raise SystemExit(main())
