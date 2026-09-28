"""Bounded real-Inno servicing matrix using mandatory marked temporary roots."""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
from application_lifetime import mutex_prefix, windows_api
from servicing_inventory import INVENTORY_NAME, load_inventory, verify_payload
from servicing_paths import FIXTURE_MARKER, validate_roots
from tools.build_installer import build_installer
from tools.servicing_fixture import initialize_fixture, populate_profile, snapshot
from tools.servicing_smoke import launch_desktop, activity_present

HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run(arguments: list[str], root: Path, environment: dict[str, str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(arguments, cwd=root, env=environment, text=True, encoding='utf-8', errors='replace',
                          capture_output=True, timeout=timeout, creationflags=HIDDEN)


def _registration(root: Path) -> dict:
    import winreg
    identity = str(uuid.uuid5(uuid.UUID("67CE3406-96D1-4EB6-AF71-3C95D925CF8B"), str(root))).upper()
    key = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{' + identity + '}_is1'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as entry:
            return {name:winreg.QueryValueEx(entry,name)[0] for name in ('DisplayName','DisplayVersion','Publisher','InstallLocation','DisplayIcon')}
    except FileNotFoundError:
        return {}


def run_matrix(root: Path, profile: Path, payloads: tuple[Path, ...], wheel: Path,
               plugin_id: str, receipts: Path) -> dict:
    """Exercise installation/repair/upgrade/uninstall only in validated test roots.

    Args:
        root: Marked temporary fixture root; no live-path defaults.
        profile: Explicit root/profile destination.
        payloads: Frozen synthetic A, B, API1 successor, and API2 successor builds.
        wheel: Independently built external sample wheel.
        plugin_id: Expected sample plugin ID.
        receipts: Explicit durable output directory outside the disposable profile.

    Returns:
        Structured matrix observations, emitted after each checkpoint.

    Raises:
        ValueError: Roots, payloads, or version sequence are unsafe or invalid.
        AssertionError: A required servicing guarantee fails.
        subprocess.TimeoutExpired: Any process exceeds its bounded run time.
    """
    app, profile = validate_roots(root / 'app', profile, root / FIXTURE_MARKER)
    if len(payloads) != 4 or receipts == profile or profile in receipts.parents:
        raise ValueError('Four synthetic payloads and separate durable receipts are required')
    inventories = tuple(load_inventory(path / INVENTORY_NAME) for path in payloads)
    if tuple(item.version for item in inventories) != ('1.5.0','1.5.1','2.0.0','2.0.0'):
        raise ValueError('Unexpected synthetic version matrix')
    receipts.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(CHESSWIZARD_DATA_DIR=str(profile), PYTHONPATH='',
                       PATH=os.pathsep.join([str(Path(os.environ['SystemRoot'])/'System32'), os.environ['SystemRoot']]))
    result = {'environment':'isolated same-host Windows; not clean-machine certification', 'fixture':str(root), 'steps':[]}
    def record(name: str, **values: object) -> None:
        result['steps'].append(dict(step=name, **values))
        (receipts/'matrix.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(name, json.dumps(values), flush=True)
    setups = []
    for index, payload in enumerate(payloads):
        setups.append(build_installer(payload, receipts / ('installer-'+str(index)), root))
    record('compiled', installers=[str(p) for p in setups])
    def setup(index: int, label: str, expect_success: bool = True, extra: tuple[str, ...] = ()) -> None:
        before = snapshot(profile)
        completed = _run([str(setups[index]), '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',
                          '/LOG='+str(receipts/(label+'.log')), *extra], root, environment)
        assert (completed.returncode == 0) == expect_success, (label, completed.returncode, completed.stdout, completed.stderr)
        assert snapshot(profile) == before, 'Installer modified user profile'
        record(label, exit_code=completed.returncode, profile_unchanged=True)
    def host(*arguments: str, success: bool = True) -> dict:
        completed = _run([str(app/'ChessWizardPluginHost.exe'), *arguments, '--profile',str(profile)], root, environment)
        assert (completed.returncode == 0) == success, completed.stdout+completed.stderr
        return json.loads(completed.stdout)
    def uninstall(label: str, full: bool = False) -> None:
        before = snapshot(profile)
        extra = ['/SERVICINGTESTREMOVE=confirmed-disposable-profile'] if full else []
        completed = _run([str(app/'unins000.exe'),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',
                          '/LOG='+str(receipts/(label+'.log')), *extra], root, environment)
        assert completed.returncode == 0, (label,completed.returncode)
        assert not _registration(root), 'Uninstall entry retained'
        assert not (root/'desktop/ChessWizard.lnk').exists()
        assert not (root/'start-menu/ChessWizard.lnk').exists()
        assert not (app/'ChessWizard.exe').exists()
        if full:
            assert not profile.exists(), 'Confirmed disposable full removal did not remove profile'
        else:
            assert snapshot(profile) == before
        assert (app/'unknown-user-file.txt').read_text() == 'Preserve unknown bytes'
        record(label, exit_code=completed.returncode, profile_removed=full, profile_preserved=not full, unknown_preserved=True)
    setup(0,'clean-install')
    verify_payload(app,inventories[0])
    assert (root/'desktop/ChessWizard.lnk').is_file() and (root/'start-menu/ChessWizard.lnk').is_file()
    registration = _registration(root)
    assert registration['DisplayVersion']=='1.5.0' and registration['Publisher']=='ChessWizard contributors'
    assert Path(registration['InstallLocation'].rstrip('\\'))==app
    record('integration',registration=registration,desktop_default=True,start_menu=True)
    record('fresh-desktop-launch', **launch_desktop(root,environment,'1.5.0'))
    info = host('info'); assert info['frozen'] and info['api_version']=='1.0.0'
    record('frozen-runtime',info=info)
    populate_profile(profile)
    installed=host('install',str(wheel))
    host('enable',plugin_id,'--acknowledge-code-trust')
    fen='rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
    assert host('analyze',plugin_id,'--fen',fen)['validated_by_core']
    protected=snapshot(profile)
    package_identity=snapshot(profile/'plugins/installations')
    record('synthetic-data-and-plugin',installation=installed,profile_files=len(protected))
    # Keep a real frozen worker blocked on input to prove setup never kills it.
    worker=subprocess.Popen([str(app/'ChessWizardPluginHost.exe'),'worker'],cwd=root,env=environment,
                            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=HIDDEN)
    try:
        deadline=time.monotonic()+15
        while not activity_present(app) and time.monotonic()<deadline: time.sleep(0.05)
        assert activity_present(app) and worker.poll() is None
        setup(0,'running-host-refused',False)
        assert worker.poll() is None, 'Installer terminated active host'
        worker.communicate(b'{}',timeout=15)
        assert not activity_present(app), 'Worker lifetime survived termination'
        record('host-drained',no_orphaned_host=True)
    finally:
        if worker.poll() is None: worker.terminate();worker.wait(timeout=10)
    (app/'unknown-user-file.txt').write_text('Preserve unknown bytes')
    (app/'ChessWizard.exe').write_bytes(b'corrupt owned executable')
    (app/'_internal/LICENSE').unlink()
    setup(0,'same-version-repair')
    verify_payload(app,inventories[0])
    setup(0,'same-version-idempotent-repair')
    assert len(list((root/'desktop').glob('*.lnk')))==1 and len(list((root/'start-menu').glob('*.lnk')))==1
    old=snapshot(app)
    with (app/'_internal/LICENSE').open('rb'):
        setup(1,'locked-owned-file-refused',False)
    assert snapshot(app)==old
    setup(1,'invalid-inventory-refused',False,('/SERVICINGTESTFAIL=invalid-inventory',))
    assert snapshot(app)==old
    for mode in ('pre-mutation','reversible','validation'):
        setup(1,'failure-'+mode,False,('/SERVICINGTESTFAIL='+mode,))
        # Inno's own binary log may change; application inventory and owned bytes must restore.
        for item in inventories[0].files:
            assert snapshot(app).get(item.path)==old[item.path], ('rollback mismatch',mode,item.path)
        assert not (app/'new-owned.txt').exists()
    setup(1,'upgrade-1.5.1')
    verify_payload(app,inventories[1])
    assert not (app/'old_module.py').exists() and not (app/'stale.dll').exists()
    assert host('analyze',plugin_id,'--fen',fen)['validated_by_core']
    assert snapshot(profile/'plugins/installations')==package_identity
    record('compatible-1.5.1',artifact_unchanged=True,usable=True,stale_removed=True)
    before=snapshot(app)
    setup(0,'downgrade-refused',False)
    assert snapshot(app)==before
    setup(2,'upgrade-2.0-api1')
    assert host('info')['api_version']=='1.0.0'
    assert host('analyze',plugin_id,'--fen',fen)['validated_by_core']
    assert snapshot(profile/'plugins/installations')==package_identity
    record('compatible-2.0-api1',artifact_unchanged=True,usable=True)
    uninstall('default-uninstall')
    # A previous uninstall can leave unknown files; reinstall must preserve them.
    setup(2,'reinstall-preserve')
    assert host('analyze',plugin_id,'--fen',fen)['validated_by_core']
    setup(3,'upgrade-2.0-api2')
    assert host('info')['api_version']=='2.0.0'
    state=host('list')
    assert state['plugins'] and state['plugins'][0]['runtime_state']=='blocked', state
    assert snapshot(profile/'plugins/installations')==package_identity
    record('incompatible-api2',retained=True,view=state['plugins'][0])
    record('incompatible-desktop-launch', **launch_desktop(root,environment,'2.0.0'))
    uninstall('full-data-uninstall',True)
    setup(3,'reinstall-fresh')
    assert host('list')['plugins']==[]
    assert not (profile/'merlin.db').exists()
    record('fresh-profile',old_data_absent=True,plugins=[])
    record('fresh-reinstall-launch', **launch_desktop(root,environment,'2.0.0'))
    uninstall('final-app-cleanup')
    result['status']='PASS'
    (receipts/'matrix.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result


def main() -> int:
    """Run only explicitly configured disposable servicing validation.

    Returns:
        Zero for a completed matrix; errors remain visible with partial receipts.
    """
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture',type=Path,required=True)
    parser.add_argument('--profile',type=Path,required=True)
    parser.add_argument('--initialize',action='store_true')
    parser.add_argument('--payloads',type=Path,nargs=4,required=True)
    parser.add_argument('--wheel',type=Path,required=True)
    parser.add_argument('--plugin-id',required=True)
    parser.add_argument('--receipts',type=Path,required=True)
    args=parser.parse_args()
    if args.initialize: initialize_fixture(args.fixture,args.profile)
    run_matrix(args.fixture,args.profile,tuple(p.absolute() for p in args.payloads),args.wheel.absolute(),args.plugin_id,args.receipts.absolute())
    return 0


if __name__=='__main__':
    raise SystemExit(main())
