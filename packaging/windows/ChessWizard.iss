#ifndef AppVersion
  #error AppVersion is supplied from the canonical build inventory
#endif
#ifndef PayloadDir
  #error PayloadDir must identify the verified onedir build
#endif
#ifndef OutputPath
  #error OutputPath is required
#endif
#ifdef FixtureRoot
  #define ProductIdentity "{{" + FixtureId + "}"
#else
  #define ProductIdentity "{{67CE3406-96D1-4EB6-AF71-3C95D925CF8B}"
#endif

[Setup]
AppId={#ProductIdentity}
AppName=ChessWizard
AppVersion={#AppVersion}
AppPublisher=ChessWizard contributors
#ifdef FixtureRoot
DefaultDirName={#FixtureRoot}\app
#else
DefaultDirName={localappdata}\Programs\ChessWizard
#endif
DefaultGroupName=ChessWizard
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
MinVersion=10.0
OutputDir={#OutputPath}
OutputBaseFilename=ChessWizard-{#AppVersion}-Windows-x64-Setup
SetupIconFile=assets\ChessWizard.ico
UninstallDisplayIcon={app}\ChessWizard.exe
LicenseFile=..\..\LICENSE
#ifdef FixtureRoot
Compression=none
SolidCompression=no
#else
Compression=lzma2
SolidCompression=yes
#endif
WizardStyle=modern
UsePreviousTasks=yes
CloseApplications=no
RestartApplications=no
Uninstallable=yes
SetupLogging=yes
AppMutex={code:ActivityMutex}

[Tasks]
Name: desktopicon; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Excludes: "chesswizard-payload.json"; Flags: ignoreversion recursesubdirs createallsubdirs; AfterInstall: PayloadCopied
Source: "{#PayloadDir}\chesswizard-payload.json"; DestDir: "{app}"; Flags: ignoreversion; AfterInstall: ValidateInstalled

[Icons]
#ifdef FixtureRoot
Name: "{#FixtureRoot}\desktop\ChessWizard"; Filename: "{app}\ChessWizard.exe"; WorkingDir: "{app}"; IconFilename: "{app}\ChessWizard.exe"; Tasks: desktopicon
Name: "{#FixtureRoot}\start-menu\ChessWizard"; Filename: "{app}\ChessWizard.exe"; WorkingDir: "{app}"; IconFilename: "{app}\ChessWizard.exe"
#else
Name: "{userdesktop}\ChessWizard"; Filename: "{app}\ChessWizard.exe"; WorkingDir: "{app}"; IconFilename: "{app}\ChessWizard.exe"; Tasks: desktopicon
Name: "{userprograms}\ChessWizard\ChessWizard"; Filename: "{app}\ChessWizard.exe"; WorkingDir: "{app}"; IconFilename: "{app}\ChessWizard.exe"
#endif

[Run]
Filename: "{app}\ChessWizard.exe"; Description: "Launch ChessWizard"; Flags: nowait postinstall skipifsilent unchecked

[Code]
var
  ServicingHandle: THandle;
  Helper, TransactionDir: String;
  Prepared, Finalized, RemoveData, ServicingFailed: Boolean;
  CopiedFiles: Integer;

function CreateMutexW(Attributes: LongWord; InitialOwner: Boolean; Name: String): THandle;
  external 'CreateMutexW@kernel32.dll stdcall';
function WaitForSingleObject(Handle: THandle; Milliseconds: Cardinal): Cardinal;
  external 'WaitForSingleObject@kernel32.dll stdcall';
function ReleaseMutex(Handle: THandle): Boolean;
  external 'ReleaseMutex@kernel32.dll stdcall';
function CloseHandle(Handle: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

function LifetimePrefix: String;
begin
#ifdef FixtureRoot
  Result := '{#FixtureRoot}\app';
#else
  Result := ExpandConstant('{localappdata}\Programs\ChessWizard');
#endif
  Result := 'Global\ChessWizard-' + GetSHA256OfUnicodeString(LowerCase(RemoveBackslashUnlessRoot(ExpandFileName(Result))));
end;

function ActivityMutex(Param: String): String;
begin
  Result := LifetimePrefix + '-activity';
end;

function BeginServicing: Boolean;
var Gate: THandle; WaitResult: Cardinal;
begin
  Result := False;
  if ServicingHandle <> 0 then begin Result := True; exit; end;
  Gate := CreateMutexW(0, False, LifetimePrefix + '-gate');
  if Gate = 0 then exit;
  WaitResult := WaitForSingleObject(Gate, 5000);
  if (WaitResult = 0) or (WaitResult = $80) then begin
    if not CheckForMutexes(ActivityMutex('') + ',' + LifetimePrefix + '-servicing') then begin
      ServicingHandle := CreateMutexW(0, False, LifetimePrefix + '-servicing');
      Result := ServicingHandle <> 0;
    end;
    ReleaseMutex(Gate);
  end;
  CloseHandle(Gate);
end;

function ProfileRoot: String;
begin
#ifdef FixtureRoot
  Result := '{#FixtureRoot}\profile';
#else
  Result := ExpandConstant('{localappdata}\ChessWizard');
#endif
end;

function BaseArguments: String;
begin
  Result := ' --app ' + AddQuotes(ExpandConstant('{app}')) + ' --profile ' + AddQuotes(ProfileRoot);
#ifdef FixtureRoot
  Result := Result + ' --fixture ' + AddQuotes('{#FixtureRoot}\.chesswizard-servicing-fixture.json');
#endif
end;

function RunHelper(Action, Extra, ReceiptName: String): Boolean;
var ExitCode: Integer; Receipt: String; Output: AnsiString;
begin
  Receipt := ExpandConstant('{tmp}\') + ReceiptName + '.json';
  Result := Exec(Helper, Action + BaseArguments + Extra + ' --receipt ' + AddQuotes(Receipt),
    ExpandConstant('{tmp}'), SW_HIDE, ewWaitUntilTerminated, ExitCode) and (ExitCode = 0);
  if LoadStringFromFile(Receipt, Output) then Log(Output);
  if not Result then Log('Servicing action failed: ' + Action + '. See JSON result above; keep user data and rerun the same/newer installer for repair.');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not BeginServicing then begin
    Result := 'Close ChessWizard and its plugin hosts cleanly, then retry setup. No processes were stopped.';
    exit;
  end;
#ifdef FixtureRoot
  if ExpandConstant('{param:SERVICINGTESTFAIL|}') = 'pre-mutation' then begin
    Result := 'Disposable test cancellation before mutation'; exit;
  end;
#endif
  ExtractTemporaryFiles('{app}\*');
#ifdef FixtureRoot
  if ExpandConstant('{param:SERVICINGTESTFAIL|}') = 'invalid-inventory' then
    SaveStringToFile(ExpandConstant('{tmp}\') + '{app}\chesswizard-payload.json', '{}', False);
#endif
  Helper := ExpandConstant('{tmp}\') + '{app}\ChessWizardServicing.exe';
  TransactionDir := ExpandConstant('{tmp}\chesswizard-rollback');
  if not RunHelper('prepare', ' --source ' + AddQuotes(ExpandConstant('{tmp}\') + '{app}') +
    ' --transaction ' + AddQuotes(TransactionDir), 'prepare') then begin
    Result := 'Preflight refused installation. Review the setup log; close file users or use the same/newer repair installer. Application and user data were not changed.';
    exit;
  end;
  Prepared := True;
end;

procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  if ServicingFailed then begin Cancel := True; Confirm := False; end;
end;

procedure CancelFailedInstall(Reason: String);
begin
  ServicingFailed := True;
  Log(Reason);
  SuppressibleMsgBox(Reason + ' Your ChessWizard data was kept. Rerun the same/newer installer if repair is needed.', mbError, MB_OK, IDOK);
  // Inno catches AfterInstall exceptions. Use its cancellation path instead.
  // Its Close handler requires a visible enabled form even in very-silent mode.
  if WizardSilent then begin WizardForm.Left := -10000; WizardForm.Top := -10000; end;
  WizardForm.Enabled := True;
  WizardForm.CancelButton.Enabled := True;
  WizardForm.Show;
  WizardForm.Close;
end;

function InitializeSetup: Boolean;
var I: Integer;
begin
  Result := True;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), '/NOCANCEL') = 0 then begin
      Log('/NOCANCEL is unsupported: servicing must retain its fail-closed cancellation path.');
      Result := False;
    end;
end;

procedure PayloadCopied;
begin
  CopiedFiles := CopiedFiles + 1;
#ifdef FixtureRoot
  if (ExpandConstant('{param:SERVICINGTESTFAIL|}') = 'reversible') and (CopiedFiles = 2) then
    CancelFailedInstall('Disposable cancellation during reversible file-copy stage');
#endif
end;

procedure ValidateInstalled;
begin
#ifdef FixtureRoot
  if ExpandConstant('{param:SERVICINGTESTFAIL|}') = 'validation' then
    SaveStringToFile(ExpandConstant('{app}\new-owned.txt'), 'Injected test corruption before validation', False);
#endif
  if not RunHelper('validate', ' --transaction ' + AddQuotes(TransactionDir), 'validate') then
    CancelFailedInstall('Installed payload failed pre-finalization verification. See setup log and repair guidance.');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  // Inno has finalized installation by ssPostInstall. Never promise rollback after it.
  if CurStep = ssPostInstall then begin
    Finalized := True;
    // Release before the Finished page can launch the guarded desktop.
    if ServicingHandle <> 0 then begin CloseHandle(ServicingHandle); ServicingHandle := 0; end;
  end;
end;

procedure DeinitializeSetup;
begin
  if Prepared and not Finalized then begin
    if not RunHelper('rollback', ' --transaction ' + AddQuotes(TransactionDir), 'rollback') then
      SuppressibleMsgBox('Application rollback could not complete. Your ChessWizard data was kept. Close file users and rerun this installer to repair before launching ChessWizard.', mbError, MB_OK, IDOK);
  end;
  if ServicingHandle <> 0 then CloseHandle(ServicingHandle);
end;

function InitializeUninstall: Boolean;
var Page: TSetupForm; Choice: TNewCheckBox; Explanation: TNewStaticText;
    ContinueButton, CancelButton: TNewButton;
begin
  Result := True;
  RemoveData := False;
#ifdef FixtureRoot
  if ExpandConstant('{param:SERVICINGTESTREMOVE|}') = 'confirmed-disposable-profile' then begin
    RemoveData := True; exit;
  end;
#endif
  if UninstallSilent then begin
    Log('Your ChessWizard data will be kept. Silent uninstall never removes user data.');
    exit;
  end;
  Page := CreateCustomForm(ScaleX(510), ScaleY(220), False, False);
  try
    Page.Caption := 'Remove ChessWizard';
    Explanation := TNewStaticText.Create(Page); Explanation.Parent := Page;
    Explanation.SetBounds(ScaleX(16), ScaleY(16), ScaleX(476), ScaleY(60));
    Explanation.AutoSize := False; Explanation.WordWrap := True;
    Explanation.Caption := 'Your ChessWizard data will be kept.' + #13#10 +
      'Uninstall removes the application and its shortcuts.';
    Choice := TNewCheckBox.Create(Page); Choice.Parent := Page;
    Choice.SetBounds(ScaleX(16), ScaleY(90), ScaleX(476), ScaleY(28));
    Choice.Caption := 'Also remove all local ChessWizard data'; Choice.Checked := False;
    ContinueButton := TNewButton.Create(Page); ContinueButton.Parent := Page;
    ContinueButton.SetBounds(ScaleX(298), ScaleY(165), ScaleX(92), ScaleY(28));
    ContinueButton.Caption := 'Continue'; ContinueButton.ModalResult := mrOk;
    CancelButton := TNewButton.Create(Page); CancelButton.Parent := Page;
    CancelButton.SetBounds(ScaleX(398), ScaleY(165), ScaleX(92), ScaleY(28));
    CancelButton.Caption := 'Cancel'; CancelButton.ModalResult := mrCancel; CancelButton.Cancel := True;
    Result := Page.ShowModal = mrOk;
    RemoveData := Result and Choice.Checked;
  finally
    Page.Free;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var PreviewFile: String;
begin
  if CurUninstallStep = usUninstall then begin
    if not BeginServicing then
      RaiseException('Close ChessWizard and plugin hosts cleanly, then retry. No processes were stopped.');
    Helper := ExpandConstant('{app}\ChessWizardServicing.exe');
    if not RunHelper('uninstall-check', '', 'uninstall-check') then
      RaiseException('Unsafe application path or linked content. Uninstall stopped; user data was kept.');
    if RemoveData then begin
      if not RunHelper('preview-removal', '', 'profile-removal-preview') then
        RaiseException('Custom, linked, or unsafe user data cannot be removed automatically. Keep data and review the location manually.');
      PreviewFile := ExpandConstant('{tmp}\profile-removal-preview.json');
#ifdef FixtureRoot
      if ExpandConstant('{param:SERVICINGTESTREMOVE|}') <> 'confirmed-disposable-profile' then
#endif
      if MsgBox('Remove all ChessWizard data?' + #13#10 + #13#10 +
        'This permanently deletes local game history, settings, openings, training/reviews, themes, caches, and installed plugins from:' + #13#10 +
        ProfileRoot + #13#10 + #13#10 + 'This cannot be undone. Continue with permanent removal?', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) <> IDYES then
        RaiseException('Full-data removal cancelled; user data was kept.');
      if not RunHelper('remove-profile', ' --preview ' + AddQuotes(PreviewFile) +
        ' --confirm "REMOVE ALL LOCAL CHESSWIZARD DATA"', 'profile-removal') then
        RaiseException('Full-data removal did not complete. Review the log; deletion is irreversible and may be partial.');
    end else Log('Your ChessWizard data will be kept.');
  end;
end;

procedure DeinitializeUninstall;
begin
  if ServicingHandle <> 0 then CloseHandle(ServicingHandle);
end;
