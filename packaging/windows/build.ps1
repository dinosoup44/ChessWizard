param([switch]$Smoke, [switch]$PluginSpike, [string]$SyntheticVersion = "", [ValidateSet("", "1.0.0", "2.0.0")][string]$SyntheticApi = "", [ValidatePattern("^rehearsal(?:-[a-z0-9]+)*$")][string]$Rehearsal = "rehearsal-import")
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$buildPython = Join-Path $projectRoot 'build/windows/venv/Scripts/python.exe'
$originalPath = $env:PATH
$originalPythonPath = $env:PYTHONPATH
$originalSmoke = $env:CHESSWIZARD_BUILD_SMOKE
$originalRehearsal = $env:CHESSWIZARD_REHEARSAL
$originalSyntheticVersion = $env:CHESSWIZARD_SYNTHETIC_VERSION
$originalSyntheticApi = $env:CHESSWIZARD_SYNTHETIC_API
$originalPluginSpike = $env:CHESSWIZARD_BUILD_PLUGIN_SPIKE
try {
    $pythonBase = & $buildPython -c 'import sys; print(sys.base_prefix)'
    $env:PATH = "$pythonBase;$pythonBase\DLLs;$env:SystemRoot\System32;$env:SystemRoot"
    $env:PYTHONPATH = ''
    $env:PYTHONUTF8 = '1'
    $env:PYTHONHASHSEED = '0'
    $env:CHESSWIZARD_SYNTHETIC_VERSION = $SyntheticVersion
    $env:CHESSWIZARD_SYNTHETIC_API = $SyntheticApi
    $env:CHESSWIZARD_BUILD_SMOKE = $(if ($Smoke) { '1' } else { '0' })
    $env:CHESSWIZARD_REHEARSAL = $Rehearsal
    $env:CHESSWIZARD_BUILD_PLUGIN_SPIKE = $(if ($PluginSpike) { '1' } else { '0' })
    & $buildPython -B -m PyInstaller --clean --noconfirm --distpath (Join-Path $projectRoot 'dist') --workpath (Join-Path $projectRoot "build/windows/pyinstaller-$Rehearsal") (Join-Path $PSScriptRoot 'ChessWizard.spec')
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed: $LASTEXITCODE" }
} finally {
    $env:CHESSWIZARD_SYNTHETIC_VERSION = $originalSyntheticVersion
    $env:CHESSWIZARD_SYNTHETIC_API = $originalSyntheticApi
    $env:PATH = $originalPath
    $env:PYTHONPATH = $originalPythonPath
    $env:CHESSWIZARD_BUILD_SMOKE = $originalSmoke
    $env:CHESSWIZARD_REHEARSAL = $originalRehearsal
    $env:CHESSWIZARD_BUILD_PLUGIN_SPIKE = $originalPluginSpike
}
