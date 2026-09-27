; Per-user, offline ONEDIR installer. Version and payload are supplied by build-installer.ps1.
#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef PayloadDir
  #error PayloadDir is required
#endif
#ifndef OutputPath
  #error OutputPath is required
#endif
[Setup]
AppId={{67CE3406-96D1-4EB6-AF71-3C95D925CF8B}
AppName=ChessWizard
AppVersion={#AppVersion}
AppPublisher=ChessWizard contributors
DefaultDirName={localappdata}\Programs\ChessWizard
DefaultGroupName=ChessWizard
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputPath}
OutputBaseFilename=ChessWizard-{#AppVersion}-Windows-x64-Setup
SetupIconFile=assets\ChessWizard.ico
UninstallDisplayIcon={app}\ChessWizard.exe
LicenseFile=..\..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UsePreviousTasks=no
CloseApplications=yes
RestartApplications=no
Uninstallable=yes

[Tasks]
Name: desktopicon; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\licenses\inno-setup\LICENSE.txt"; DestDir: "{app}\_internal\licenses\inno-setup"; Flags: ignoreversion

[Icons]
Name: "{userdesktop}\ChessWizard"; Filename: "{app}\ChessWizard.exe"; WorkingDir: "{app}"; IconFilename: "{app}\ChessWizard.exe"; Tasks: desktopicon
Name: "{userprograms}\ChessWizard\ChessWizard"; Filename: "{app}\ChessWizard.exe"; WorkingDir: "{app}"; IconFilename: "{app}\ChessWizard.exe"

[Run]
Filename: "{app}\ChessWizard.exe"; Description: "Launch ChessWizard"; Flags: nowait postinstall skipifsilent unchecked

; There are intentionally no user-data deletion actions or registry data settings.
; The application owns a separate LocalAppData\ChessWizard profile.
