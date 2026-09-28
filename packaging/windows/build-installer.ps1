param([Parameter(Mandatory=$true)][string]$PayloadDir,
      [Parameter(Mandatory=$true)][string]$OutputPath,
      [string]$FixtureRoot='')
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$buildPython=Join-Path $projectRoot 'build/windows/venv/Scripts/python.exe'
Push-Location $projectRoot
try {
    $buildArgs=@('-B','-m','tools.build_installer','--payload',$PayloadDir,'--output',$OutputPath)
    if ($FixtureRoot) { $buildArgs+=@('--fixture',$FixtureRoot) }
    & $buildPython @buildArgs
    if ($LASTEXITCODE -ne 0) { throw "Installer build failed: $LASTEXITCODE" }
} finally { Pop-Location }
