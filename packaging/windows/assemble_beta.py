"""Assemble public beta artifacts from exact frozen inputs, never the project tree."""
import ast
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT=Path(__file__).resolve().parents[2]
OUTPUT=ROOT.parent/'ChessWizard_Beta_Distribution'
REPORT=ROOT/'reports/beta_installer'

WORK=ROOT/'build/windows/pyinstaller-rehearsal-beta-installer/ChessWizard'


import sys
sys.path.insert(0, str(ROOT))
from chesswizard_version import VERSION
FROZEN=ROOT/('dist/ChessWizard-'+VERSION+'-rehearsal-beta-installer')
from tools.package_privacy import PrivacyPolicy, content_findings, load_privacy_policy, validate_package_path

def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def validate_sources(source: dict[str, Path], privacy: PrivacyPolicy = PrivacyPolicy()) -> None:
    """Validate source-companion members before any archive is created.

    Args:
        source: Relative archive names mapped to exact files to inspect.
        privacy: Optional private literals supplied through local configuration.

    Raises:
        ValueError: A member path or file content contains private material.
        OSError: A source file cannot be read.
    """
    for name,path in source.items():
        validate_package_path(name, privacy)
        if name.startswith('ChessWizard/') and path.suffix.lower() in ('.py','.md','.txt','.json','.ps1','.iss','.spec'):
            if content_findings(path.read_bytes(), privacy):
                raise ValueError('Private content in corresponding source member: '+name)


def build(privacy: PrivacyPolicy = PrivacyPolicy()) -> None:
    """Assemble already-approved frozen artifacts after generic privacy validation.

    Args:
        privacy: Additional owner-local identifiers supplied outside public source.

    Raises:
        ValueError: A private source member or content finding is detected.
        AssertionError: Existing exact-build acceptance or integrity checks fail.
        OSError: Required artifacts cannot be read or output cannot be written.
    """
    from chesswizard_version import VERSION as current
    assert current==VERSION
    assert json.loads((REPORT/'license_closure.json').read_text(encoding='utf-8-sig'))['errors']==[]
    assert json.loads((REPORT/'installer_acceptance.json').read_text())['result']=='PASS'
    inventory=json.loads((REPORT/'package_manifest.json').read_text())
    for entry in inventory['files']:assert digest(FROZEN/entry['path'])==entry['sha256']
    source={}
    def add(path,name):
        assert name not in source and '..' not in Path(name).parts
        source[name]=Path(path)
    source_inputs = {name for toc in WORK.glob('PYZ-*.toc') for _,name,_ in ast.literal_eval(toc.read_text())[1]}
    for name in sorted(source_inputs):
        path=Path(name).resolve()
        if path.is_relative_to(ROOT) and not path.is_relative_to(ROOT/'build'):
            add(path,'ChessWizard/'+path.relative_to(ROOT).as_posix())
    for entry in ('run_chesswizard.py','plugin_host.py','servicing_host.py'):
        if 'ChessWizard/'+entry not in source: add(ROOT/entry,'ChessWizard/'+entry)
    for entry in json.loads((ROOT/'licenses/release_files.json').read_text()):
        if 'ChessWizard/'+entry['path'] not in source:add(ROOT/entry['path'],'ChessWizard/'+entry['path'])
    for path in (ROOT/'licenses/inno-setup').glob('*'):add(path,'ChessWizard/'+path.relative_to(ROOT).as_posix())
    for name in ('ChessWizard.spec','ChessWizard.iss','build.ps1','build-installer.ps1','requirements-build.lock.txt','requirements-build.txt','installer-toolchain.json','BUILD_BETA.md'):
        add(ROOT/'packaging/windows'/name,'ChessWizard/packaging/windows/'+name)
    for path in (ROOT/'packaging/windows/assets').iterdir():add(path,'ChessWizard/packaging/windows/assets/'+path.name)
    for path in (FROZEN/'_internal/docs').glob('*.md'):add(path,'ChessWizard/docs/'+path.name)
    add(REPORT/'package_manifest.json','ChessWizard/source_info/frozen_manifest.json')
    upstream=ROOT/'dist/source-companion-inputs'
    for entry in json.loads((upstream/'SHA256SUMS.json').read_text()):assert digest(upstream/entry['path'])==entry['sha256']
    for path in upstream.rglob('*'):
        if path.is_file():add(path,'Upstream/'+path.relative_to(upstream).as_posix())
    validate_sources(source, privacy)
    manifest=[dict(path=name,bytes=path.stat().st_size,sha256=digest(path)) for name,path in sorted(source.items())]
    companion=OUTPUT/f'ChessWizard-{VERSION}-Corresponding-Source.zip'
    with zipfile.ZipFile(companion,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name,path in sorted(source.items()):archive.write(path,name)
        archive.writestr('SOURCE-MANIFEST.json',json.dumps(manifest,indent=2))
    with zipfile.ZipFile(companion) as archive:assert archive.testzip() is None
    # A separate source archive keeps the tester's installation folder uncomplicated.
    notices=OUTPUT/'LICENSES';notices.mkdir(exist_ok=True)
    for path in (FROZEN/'_internal/licenses').rglob('*'):
        if path.is_file():
            dest=notices/path.relative_to(FROZEN/'_internal/licenses');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
    (notices/'inno-setup').mkdir(exist_ok=True)
    shutil.copyfile(ROOT/'licenses/inno-setup/LICENSE.txt',notices/'inno-setup/LICENSE.txt')
    for name in ('LICENSE','COPYING.md','THIRD_PARTY_NOTICES.md'):shutil.copyfile(FROZEN/'_internal'/name,notices/name)
    setup=OUTPUT/f'ChessWizard-{VERSION}-Windows-x64-Setup.exe'
    assert digest(setup)==json.loads((REPORT/'installer_acceptance.json').read_text())['setup_sha256']
    for name in ('README-FIRST.txt', 'SOURCE-NOTICE.txt'):
        (OUTPUT/name).write_text((ROOT/'packaging/windows/handoff'/name).read_text(encoding='utf-8').replace('{APP_VERSION}', VERSION), encoding='utf-8')
    members=[setup,OUTPUT/'README-FIRST.txt',OUTPUT/'SOURCE-NOTICE.txt']+sorted(p for p in notices.rglob('*') if p.is_file())
    archive_path=OUTPUT/f'ChessWizard-{VERSION}-Windows-x64.zip'
    with zipfile.ZipFile(archive_path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path in members:archive.write(path,path.relative_to(OUTPUT).as_posix())
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist())=={p.relative_to(OUTPUT).as_posix() for p in members}
    hashes={p.name:{'sha256':digest(p),'bytes':p.stat().st_size} for p in (setup,archive_path,companion)}
    (OUTPUT/'SHA256SUMS.txt').write_text('\n'.join(row['sha256']+'  '+name for name,row in hashes.items())+'\n',encoding='utf-8')
    handoff=OUTPUT/'ChessWizard_CURRENT_INSTALL.zip'
    with zipfile.ZipFile(handoff,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for path in members+[companion, OUTPUT/'SHA256SUMS.txt']:
            archive.write(path,path.relative_to(OUTPUT).as_posix())
    with zipfile.ZipFile(handoff) as archive:
        assert archive.testzip() is None
        assert companion.name in archive.namelist()
    hashes[handoff.name]={'sha256':digest(handoff),'bytes':handoff.stat().st_size}
    (REPORT/'distribution.json').write_text(json.dumps({'artifacts':hashes,'source_files':len(manifest),'zip_members':[p.relative_to(OUTPUT).as_posix() for p in members],'source_manifest':manifest},indent=2),encoding='utf-8')
    print(json.dumps(hashes,indent=2))

if __name__=='__main__':
    import sys
    sys.path.insert(0,str(ROOT))
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--privacy-config", type=Path)
    args=parser.parse_args()
    build(load_privacy_policy(args.privacy_config))
