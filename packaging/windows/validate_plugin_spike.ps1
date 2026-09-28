# Windows-only disposable-profile proof for the current host/state protocol. Requires no Python, Git, or source checkout.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$RuntimeDirectory,
    [Parameter(Mandatory=$true)][string]$WheelPath,
    [switch]$CleanMachineAttestation
)
$ErrorActionPreference='Stop'
$runtime=(Resolve-Path -LiteralPath $RuntimeDirectory).Path
$wheel=(Resolve-Path -LiteralPath $WheelPath).Path
$executable=Join-Path $runtime 'ChessWizardPluginHost.exe'
$pluginId='org.chesswizard.example.material_inventory'
$work=Join-Path ([IO.Path]::GetTempPath()) ('ChessWizardPluginProof-'+[guid]::NewGuid().ToString('N'))
$profile=Join-Path $work 'profile'
New-Item -ItemType Directory -Path $profile | Out-Null
function Read-TreeHashes([string]$Directory) {
    $result=[ordered]@{}
    Get-ChildItem -LiteralPath $Directory -Recurse -File | Sort-Object FullName | ForEach-Object {
        $result[$_.FullName.Substring($Directory.Length+1)]=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    }
    return $result
}
function Invoke-Host([string[]]$Arguments, [bool]$ExpectFailure=$false) {
    $lines=& $executable @Arguments
    $code=$LASTEXITCODE
    $value=($lines -join [Environment]::NewLine) | ConvertFrom-Json
    if ($ExpectFailure) {
        if ($code -eq 0 -or -not $value.error) { throw 'Expected rejection did not occur' }
    } elseif ($code -ne 0) { throw ('Frozen host failed: '+$value.error) }
    return $value
}
function Invoke-Worker([hashtable]$Request, [bool]$ExpectFailure=$false) {
    $Request.protocol_version=1
    $Request.nonce=[guid]::NewGuid().ToString('N')
    $requestJson=$Request | ConvertTo-Json -Compress -Depth 8
    $lines=@($requestJson | & $executable worker)
    $code=$LASTEXITCODE
    $frames=@($lines | ForEach-Object { $_ | ConvertFrom-Json })
    foreach ($frame in $frames) {
        if ($frame.protocol_version -ne 1 -or $frame.nonce -ne $Request.nonce) { throw 'Invalid worker protocol identity' }
    }
    $final=$frames[-1]
    if ($ExpectFailure) {
        if ($code -eq 0 -or $final.kind -ne 'error') { throw 'Expected worker rejection missing' }
        return $final
    }
    if ($code -ne 0 -or $final.kind -ne 'result') { throw 'Worker did not complete' }
    return $final.payload
}
function Assert-Condition([bool]$Condition,[string]$Message) {
    if (-not $Condition) { throw $Message }
}
$originalPath=$env:PATH
$originalPythonPath=$env:PYTHONPATH
$originalData=$env:CHESSWIZARD_DATA_DIR
$originalLocation=Get-Location
try {
    $runtimeBefore=Read-TreeHashes $runtime
    foreach ($relative in @('merlin.db','settings.json','opening_books/synthetic.cwbook','reviews/synthetic.txt')) {
        $target=Join-Path $profile $relative
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
        [IO.File]::WriteAllText($target,'Synthetic preservation sentinel, never production data.')
    }
    $dataBefore=Read-TreeHashes $profile
    $visibleTools=@(Get-Command python,python3,git,code -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name)
    $env:PATH="$env:SystemRoot\System32;$env:SystemRoot"
    $env:PYTHONPATH=''
    $env:CHESSWIZARD_DATA_DIR=$profile
    Set-Location -LiteralPath $work
    $info=Invoke-Host @('info')
    Assert-Condition $info.frozen 'Expected frozen host'
    Assert-Condition ($info.plugin_packages_loaded.Count -eq 0) 'Plugin already loaded'
    $installed=Invoke-Host @('install',$wheel,'--profile',$profile)
    Assert-Condition ($installed.inserted -and $installed.descriptor.compatible) 'Install failed'
    $afterInstall=Read-TreeHashes $profile
    $repeat=Invoke-Host @('install',$wheel,'--profile',$profile)
    Assert-Condition (-not $repeat.inserted) 'Identical install must reuse'
    Assert-Condition (($afterInstall | ConvertTo-Json -Compress) -eq ((Read-TreeHashes $profile) | ConvertTo-Json -Compress)) 'Identical install changed bytes'
    $listed=Invoke-Host @('list','--profile',$profile)
    Assert-Condition (-not $listed.plugins[0].requested.enabled) 'New plugin must start disabled'
    $state=Get-Content -LiteralPath (Join-Path $profile 'plugins/state.json') -Raw | ConvertFrom-Json
    $entry=@($state.installations.PSObject.Properties)[0].Value
    $site=Join-Path $profile ('plugins/installations/'+$entry.installation_id+'/site-packages')
    $request=@{operation='discover';site=$site}
    $discovery=Invoke-Worker $request
    Assert-Condition ($LASTEXITCODE -eq 0 -and $discovery.plugin_modules_loaded.Count -eq 0) 'Metadata imported plugin'
    $noTrust=Invoke-Host @('enable',$pluginId,'--profile',$profile) $true
    Assert-Condition ($noTrust.message -match 'trust') 'Trust acknowledgement was not required'
    $enabled=Invoke-Host @('enable',$pluginId,'--acknowledge-code-trust','--profile',$profile)
    Assert-Condition $enabled.changed 'Enable did not change state'
    $positions=@(
        @{fen='rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';pieces=32},
        @{fen='4k3/8/8/8/8/8/3Q4/4K3 w - - 0 1';pieces=3}
    )
    $results=@()
    foreach ($position in $positions) {
        $response=Invoke-Host @('analyze',$pluginId,'--fen',$position.fen,'--request-id','portable-proof','--profile',$profile)
        Assert-Condition $response.validated_by_core 'Core did not validate'
        Assert-Condition ($response.result.squares.Count -eq $position.pieces -and $response.result.counts.Count -eq 12) 'Incorrect inventory'
        $results+=$response
    }
    $workerRequest=@{operation='analyze';site=$site;profile=$profile;plugin_id=$pluginId;context=@{request_id='worker-proof';fen=$positions[0].fen}}
    $workerResult=Invoke-Worker $workerRequest
    Assert-Condition ($LASTEXITCODE -eq 0 -and $workerResult.worker_pid -ne $PID) 'Separate worker failed'
    $disabled=Invoke-Host @('disable',$pluginId,'--profile',$profile)
    Assert-Condition $disabled.changed 'Disable did not persist'
    $afterDisable=Read-TreeHashes $profile
    $blocked=Invoke-Host @('analyze',$pluginId,'--fen',$positions[0].fen,'--profile',$profile) $true
    Assert-Condition ($blocked.message -match 'disabled') 'Disabled invocation succeeded'
    Assert-Condition (($afterDisable | ConvertTo-Json -Compress) -eq ((Read-TreeHashes $profile) | ConvertTo-Json -Compress)) 'Disabled invocation changed bytes'
    $directDisabled=Invoke-Worker $workerRequest $true
    Assert-Condition ($directDisabled.kind -eq 'error' -and $directDisabled.error_type -eq 'PermissionError') 'Direct worker bypassed disabled state'
    $removed=Invoke-Host @('remove',$pluginId,'--profile',$profile)
    $empty=Invoke-Host @('list','--profile',$profile)
    Assert-Condition ($empty.plugins.Count -eq 0 -and -not (Test-Path -LiteralPath $site)) 'Removal incomplete'
    foreach ($name in $dataBefore.Keys) {
        Assert-Condition ((Get-FileHash -LiteralPath (Join-Path $profile $name) -Algorithm SHA256).Hash -eq $dataBefore[$name]) 'Synthetic data changed'
    }
    Assert-Condition (($runtimeBefore | ConvertTo-Json -Compress) -eq ((Read-TreeHashes $runtime) | ConvertTo-Json -Compress)) 'Frozen application changed'
    $receipt=[ordered]@{
        status='PASS'
        clean_machine_operator_attestation=[bool]$CleanMachineAttestation
        clean_machine_proof=$(if ($CleanMachineAttestation) {'Operator-attested; review environment separately'} else {'NOT ESTABLISHED by same-host test'})
        developer_commands_before_path_isolation=$visibleTools
        no_developer_commands_on_test_path=(@(Get-Command python,python3,git,code -ErrorAction SilentlyContinue).Count -eq 0)
        profile=$profile
        runtime=$runtime
        wheel_sha256=(Get-FileHash -LiteralPath $wheel -Algorithm SHA256).Hash
        frozen_info=$info
        metadata_without_import=$true
        explicit_trust_required=$true
        separate_worker_pid=$workerResult.worker_pid
        validated_positions=$results
        disabled_invocation_blocked=$true
        direct_worker_disabled_invocation_blocked=$true
        identical_install_byte_stable=$true
        plugin_removed=$true
        chess_data_preserved=$true
        core_bytes_preserved=$true
    }
    $receiptPath=Join-Path $work 'result.json'
    $receipt | ConvertTo-Json -Depth 15 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
    Write-Output "PASS: $receiptPath"
} finally {
    Set-Location -LiteralPath $originalLocation
    $env:PATH=$originalPath
    $env:PYTHONPATH=$originalPythonPath
    $env:CHESSWIZARD_DATA_DIR=$originalData
}