param([Parameter(Mandatory=$true)][string]$PayloadDir,
      [string]$OutputPath='')
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
if (-not $OutputPath) { $OutputPath=Join-Path (Split-Path $projectRoot -Parent) 'ChessWizard_Beta_Distribution' }
$compiler=Join-Path $projectRoot 'build/windows/installer-tools/inno-6.7.3/ISCC.exe'
$payload=(Resolve-Path -LiteralPath $PayloadDir).Path
$versionMatch=[regex]::Match((Get-Content -Raw (Join-Path $projectRoot 'chesswizard_version.py')), '(?m)^VERSION = "([a-zA-Z0-9.-]+)"$')
if (-not $versionMatch.Success) { throw 'Central version unavailable' }
if (-not (Test-Path -LiteralPath (Join-Path $payload 'ChessWizard.exe'))) { throw 'Missing frozen executable' }
# ISCC has a zero PE version resource; bind it to the signed pinned installer instead.
$toolchain=Get-Content -Raw (Join-Path $PSScriptRoot 'installer-toolchain.json') | ConvertFrom-Json
if ((Get-FileHash -LiteralPath $compiler -Algorithm SHA256).Hash.ToLower() -ne $toolchain.compiler_sha256) { throw 'Unreviewed installer compiler bytes' }
New-Item -ItemType Directory -Force -Path $OutputPath | Out-Null
& $compiler "/DAppVersion=$($versionMatch.Groups[1].Value)" "/DPayloadDir=$payload" "/DOutputPath=$OutputPath" (Join-Path $PSScriptRoot 'ChessWizard.iss')
if ($LASTEXITCODE -ne 0) { throw "Installer compiler failed: $LASTEXITCODE" }
