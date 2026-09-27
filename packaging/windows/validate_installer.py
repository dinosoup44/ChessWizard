"""Install/shortcut/uninstall acceptance on a disposable data profile; no owner data."""
from contextlib import closing
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT/'reports/beta_installer'
INSTALL = Path(os.environ['LOCALAPPDATA'])/'Programs/ChessWizard'
SETUP = ROOT.parent/'ChessWizard_Beta_Distribution/ChessWizard-1.0.0-beta-Windows-x64-Setup.exe'
HIDDEN = subprocess.CREATE_NO_WINDOW

def ps_literal(value):
    return "'"+str(value).replace("'", "''")+"'"

def powershell(code, *, env=None, timeout=90):
    result = subprocess.run(['powershell','-NoProfile','-Command',code],env=env,
        cwd=os.environ['TEMP'],capture_output=True,text=True,timeout=timeout,creationflags=HIDDEN)
    if result.returncode:raise RuntimeError(result.stdout+'\n'+result.stderr)
    return result.stdout.strip()

def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def tree(path):
    return {p.relative_to(path).as_posix():sha(p) for p in path.rglob('*') if p.is_file()}

def launch_shortcut(shortcut, env):
    """Use the Windows shortcut's default Open action, as Desktop double-click does."""
    pid=int(powershell('(Start-Process -FilePath '+ps_literal(shortcut)+' -PassThru).Id',env=env))
    api=ctypes.windll.user32
    api.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
    windows=[]
    callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    def inspect(hwnd,_):
        owner=wintypes.DWORD();api.GetWindowThreadProcessId(hwnd,ctypes.byref(owner))
        if owner.value==pid:
            title=ctypes.create_unicode_buffer(512);api.GetWindowTextW(hwnd,title,len(title))
            if 'ChessWizard 1.0.0-beta' in title.value:windows.append((hwnd,title.value))
        return True
    callback=callback_type(inspect)
    deadline=time.monotonic()+25
    while not windows and time.monotonic()<deadline:
        api.EnumWindows(callback,0);time.sleep(.1)
    assert windows, 'Shortcut did not open the installed versioned window'
    api.PostMessageW(windows[0][0],0x0010,0,0)
    for _ in range(100):
        if not api.IsWindow(windows[0][0]):break
        time.sleep(.1)
    assert not api.IsWindow(windows[0][0]), 'Test window failed to close normally'
    return {'pid':pid,'title':windows[0][1],'action':'Windows shell default Open on .lnk'}

def run():
    desktop=Path(powershell("[Environment]::GetFolderPath('DesktopDirectory')"))/'ChessWizard.lnk'
    menu=Path(powershell("[Environment]::GetFolderPath('Programs')"))/'ChessWizard/ChessWizard.lnk'
    assert not INSTALL.exists() and not desktop.exists() and not menu.exists(), 'Existing installation/shortcut must not be overwritten'
    assert SETUP.is_file()
    receipt={'setup_sha256':sha(SETUP),'install_path':str(INSTALL),'desktop':str(desktop),'start_menu':str(menu),'result':'RUNNING'}
    (REPORTS/'installer_acceptance.json').write_text(json.dumps(receipt,indent=2))
    args=[str(SETUP),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/LOG='+str(REPORTS/'setup-install.log')]
    subprocess.run(args,check=True,timeout=120,creationflags=HIDDEN)
    assert desktop.is_file() and menu.is_file() and (INSTALL/'ChessWizard.exe').is_file()
    receipt['default_shortcuts_created']=True
    for label,path in [('desktop_properties',desktop),('start_menu_properties',menu)]:
        code="$s=(New-Object -ComObject WScript.Shell).CreateShortcut("+ps_literal(path)+"); @{Target=$s.TargetPath;Arguments=$s.Arguments;Icon=$s.IconLocation;WorkingDirectory=$s.WorkingDirectory}|ConvertTo-Json"
        props=json.loads(powershell(code));assert Path(props['Target']).resolve()==(INSTALL/'ChessWizard.exe').resolve()
        assert props['Icon'].lower()==str(INSTALL/'ChessWizard.exe').lower()+',0'
        assert not props['Arguments'];receipt[label]=props
    manifest=json.loads((REPORTS/'package_manifest.json').read_text())
    installed=tree(INSTALL)
    for entry in manifest['files']:assert installed[entry['path']]==entry['sha256'],entry['path']
    extras=set(installed)-{e['path'] for e in manifest['files']}
    assert all(name.startswith('unins000.') or name=='_internal/licenses/inno-setup/LICENSE.txt' for name in extras),extras
    assert installed['_internal/licenses/inno-setup/LICENSE.txt']==sha(ROOT/'licenses/inno-setup/LICENSE.txt')
    receipt['installed_manifest_matches']=True;receipt['installer_only_files']=sorted(extras)
    receipt['installed_bytes']=sum(p.stat().st_size for p in INSTALL.rglob('*') if p.is_file())
    receipt['installed_inventory']=installed
    profile=Path(tempfile.mkdtemp(prefix='ChessWizard-beta-installed-'))
    receipt['isolated_profile']=str(profile)
    env=dict(os.environ,CHESSWIZARD_DATA_DIR=str(profile),LOCALAPPDATA=str(profile),
        CHESSWIZARD_AUDIT_SOURCE_ROOT=str(ROOT),PATH=os.environ['SystemRoot']+'\\System32;'+os.environ['SystemRoot'])
    env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
    receipt['desktop_launch']=launch_shortcut(desktop,env)
    with closing(sqlite3.connect((profile/'merlin.db').as_uri()+'?mode=ro',uri=True)) as db:
        names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        counts={n:db.execute('SELECT count(*) FROM "'+n+'"').fetchone()[0] for n in names}
        assert all(v==0 for n,v in counts.items() if n!='application_metadata')
        assert {'tactic_occurrences','game_collections','game_collection_members','ignored_import_games'}<=set(names)
        receipt['first_launch_counts']=counts
    helper=INSTALL/'ChessWizardSmoke.exe'
    assert not helper.exists()
    shutil.copyfile(ROOT/'build/windows/pyinstaller-rehearsal-beta-installer/ChessWizard/ChessWizardSmoke.exe',helper)
    try:
        tested=subprocess.run([str(helper),str(REPORTS/'installed_frozen_smoke.json')],cwd=profile,env=env,capture_output=True,text=True,timeout=180,creationflags=HIDDEN)
        (REPORTS/'installed_frozen_smoke.log').write_text(tested.stdout+'\n'+tested.stderr,encoding='utf-8')
        assert tested.returncode==0,tested.stderr
    finally:helper.unlink()
    evidence=json.loads((REPORTS/'installed_frozen_smoke.json').read_text())
    assert evidence['result']=='PASS'
    assert evidence['opening_library']['review_reference_selected']
    assert list((profile/'opening_books').glob('*.cwbook'))
    before_reopen=tree(profile)
    receipt['start_menu_launch']=launch_shortcut(menu,env)
    for name,digest in before_reopen.items():assert sha(profile/name)==digest, 'User evidence changed at reopen: '+name
    receipt['reopen_preserved_all_profile_files']=True
    # Keep a profile receipt for uninstall verification; never delete user-data directories.
    before_uninstall=tree(profile)
    uninstall=INSTALL/'unins000.exe'
    subprocess.run([str(uninstall),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/LOG='+str(REPORTS/'setup-uninstall.log')],check=True,timeout=90,creationflags=HIDDEN)
    deadline=time.monotonic()+30
    while INSTALL.exists() and time.monotonic()<deadline:time.sleep(.2)
    assert not INSTALL.exists() and not desktop.exists() and not menu.exists()
    assert tree(profile)==before_uninstall
    receipt.update(result='PASS',uninstall_removed_application=True,uninstall_removed_shortcuts=True,
        uninstall_preserved_profile=True,preserved_profile_files=before_uninstall,
        installed_runtime_smoke='installed_frozen_smoke.json',same_host_isolated_profile=True,
        limitation='Default choices exercised in silent mode; shortcut default Open verified. No separate physical PC or fresh Windows account was available.')
    (REPORTS/'installer_acceptance.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print('Installer / default shortcuts / installed runtime / persistence / uninstall PASS')

if __name__=='__main__':run()
