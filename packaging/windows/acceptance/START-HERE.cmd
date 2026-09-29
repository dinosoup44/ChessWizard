@echo off
setlocal
title ChessWizard V1.5 FINAL ACCEPTANCE
echo ChessWizard V1.5 FINAL ACCEPTANCE
echo Starting the acceptance guide. Keep this window open.
set "CW_ACCEPTANCE_KIT=%~dp0"
if not exist "%~dp0acceptance\ChessWizardAcceptance.exe" goto failed
"%~dp0acceptance\ChessWizardAcceptance.exe" --kit "%~dp0."
set "CW_ACCEPTANCE_EXIT=%ERRORLEVEL%"
if "%CW_ACCEPTANCE_EXIT%"=="0" exit /b 0
if "%CW_ACCEPTANCE_EXIT%"=="1" exit /b 1
if "%CW_ACCEPTANCE_EXIT%"=="2" exit /b 2
:failed
echo.
echo ========================================
echo   VALIDATION FAILED TO START OR FINISH
echo ========================================
echo No successful acceptance is recorded.
echo Do not continue release approval.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "$ErrorActionPreference='Stop'; try { $root=$env:CW_ACCEPTANCE_KIT; $folder=Join-Path $root 'receipts'; if((Get-Item -LiteralPath $root).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Linked kit refused'}; [IO.Directory]::CreateDirectory($folder)|Out-Null; if((Get-Item -LiteralPath $folder).Attributes -band [IO.FileAttributes]::ReparsePoint){throw 'Linked receipts refused'}; $path=Join-Path $folder ('launcher-'+[DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')+'.json'); @{schema_version=1;status='INCOMPLETE';current_step='Launcher failed or closed unexpectedly';utc=[DateTime]::UtcNow.ToString('o');release_approved=$false}|ConvertTo-Json|Set-Content -LiteralPath $path -Encoding UTF8; $pointer=Join-Path $folder 'latest.json'; if((Test-Path -LiteralPath $pointer) -and ((Get-Item -LiteralPath $pointer).Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Linked pointer refused'}; @{receipt=('receipts/'+[IO.Path]::GetFileName($path))}|ConvertTo-Json|Set-Content -LiteralPath $pointer -Encoding UTF8; $view=Join-Path $root 'VIEW-RESULT.txt'; if((Test-Path -LiteralPath $view) -and ((Get-Item -LiteralPath $view).Attributes -band [IO.FileAttributes]::ReparsePoint)){throw 'Linked result refused'}; @('INCOMPLETE',[DateTime]::UtcNow.ToString('o'),'Receipt: '+$path,'Next action: Keep all receipts. Reopen START-HERE.cmd. Do not approve release.')|Set-Content -LiteralPath $view -Encoding UTF8; Write-Host ('Receipt: '+$path); Write-Host ('Quick result: '+$view) } catch { Write-Host ('Could not save result: '+$_.Exception.Message); exit 1 }"
echo If no receipt could be saved, take a photo of this message.
echo Check VIEW-RESULT.txt and the receipts folder beside START-HERE.cmd.
pause
exit /b 3
