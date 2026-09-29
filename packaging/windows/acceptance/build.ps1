param()
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '../../..')).Path
$python = Join-Path $root 'build/windows/venv/Scripts/python.exe'
$output = Join-Path $root 'build/phase5-acceptance-ux/helper'
$work = Join-Path $root 'build/phase5-acceptance-ux/pyinstaller'
$spec = Join-Path $root 'build/phase5-acceptance-ux'
$originalPath = $env:PATH
$originalPythonPath = $env:PYTHONPATH
$originalUtf8 = $env:PYTHONUTF8
$originalHashSeed = $env:PYTHONHASHSEED
try {
    $pythonBase = & $python -B -c 'import sys; print(sys.base_prefix)'
    if ($LASTEXITCODE -ne 0) { throw 'Build Python unavailable' }
    $env:PATH = "$pythonBase;$pythonBase\DLLs;$env:SystemRoot\System32;$env:SystemRoot"
    $env:PYTHONPATH = ''
    $env:PYTHONUTF8 = '1'
    $env:PYTHONHASHSEED = '0'
    & $python -B -m PyInstaller --noconfirm --clean --onefile --console --name ChessWizardAcceptance --paths $root --distpath $output --workpath $work --specpath $spec --exclude-module tkinter --exclude-module chess --exclude-module PIL --exclude-module pytest --exclude-module setuptools --exclude-module pip --exclude-module installer (Join-Path $PSScriptRoot 'launcher.py')
    if ($LASTEXITCODE -ne 0) { throw 'Acceptance helper build failed' }
    $audit = 'import ast,sys; from pathlib import Path; rows=ast.literal_eval(Path(sys.argv[1]).read_text())[15]; roots=(Path(sys.base_prefix).resolve(),Path(sys.prefix).resolve()); bad=[name for name,path,kind in rows if kind in ("BINARY","EXTENSION") and not any(Path(path).resolve().is_relative_to(root) for root in roots)]; print("Unexpected native inputs:",bad); sys.exit(bool(bad))'
    & $python -B -c $audit (Join-Path $work 'ChessWizardAcceptance/EXE-00.toc')
    if ($LASTEXITCODE -ne 0) { throw 'Acceptance helper native-input audit failed; do not distribute' }
} finally {
    $env:PATH = $originalPath
    $env:PYTHONPATH = $originalPythonPath
    $env:PYTHONUTF8 = $originalUtf8
    $env:PYTHONHASHSEED = $originalHashSeed
}
