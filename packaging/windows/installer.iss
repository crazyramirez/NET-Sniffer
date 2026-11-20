; NET Sniffer — Windows installer (Inno Setup 6). Built by scripts/build.py.
; Per-user install (no administrator rights) so the app can update itself silently.

#define AppVersion GetEnv("NS_VERSION")
#define SourceDir GetEnv("NS_SOURCE")
#define OutDir GetEnv("NS_OUTDIR")
#define IconFile GetEnv("NS_ICON")

[Setup]
AppId={{8F4C2C55-6B1E-4D5B-9A57-3C2E9E1B7A10}
AppName=NET Sniffer
AppVersion={#AppVersion}
AppVerName=NET Sniffer {#AppVersion}
AppPublisher=NET Sniffer
AppPublisherURL=https://github.com/crazyramirez/NET-Sniffer
AppSupportURL=https://github.com/crazyramirez/NET-Sniffer/issues
AppUpdatesURL=https://github.com/crazyramirez/NET-Sniffer/releases/latest
DefaultDirName={localappdata}\Programs\NET Sniffer
DefaultGroupName=NET Sniffer
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
OutputDir={#OutDir}
OutputBaseFilename=NETSniffer-Setup-Windows-x64
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\NETSniffer.exe
UninstallDisplayName=NET Sniffer
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no
ShowLanguageDialog=auto
VersionInfoVersion={#AppVersion}
VersionInfoProductName=NET Sniffer

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "ja"; MessagesFile: "compiler:Languages\Japanese.isl"

[CustomMessages]
en.AutoStart=Start NET Sniffer when I sign in (runs in the system tray)
es.AutoStart=Iniciar NET Sniffer al iniciar sesión (en la bandeja del sistema)
fr.AutoStart=Lancer NET Sniffer à l'ouverture de session (zone de notification)
de.AutoStart=NET Sniffer bei der Anmeldung starten (im Infobereich)
it.AutoStart=Avvia NET Sniffer all'accesso (nell'area di notifica)
ja.AutoStart=サインイン時に NET Sniffer を起動する（システムトレイ）

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart"; Description: "{cm:AutoStart}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; never keep files from the previous version
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\NET Sniffer"; Filename: "{app}\NETSniffer.exe"; AppUserModelID: "NETSniffer.App"
Name: "{autodesktop}\NET Sniffer"; Filename: "{app}\NETSniffer.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "NETSniffer"; \
  ValueData: """{app}\NETSniffer.exe"" --background"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\NETSniffer.exe"; Description: "{cm:LaunchProgram,NET Sniffer}"; Flags: nowait postinstall skipifsilent
; silent self-update: start the new version again
Filename: "{app}\NETSniffer.exe"; Parameters: "--updated"; Flags: nowait; Check: IsRelaunch

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /T /IM NETSniffer.exe"; Flags: runhidden; RunOnceId: "KillApp"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function IsRelaunch: Boolean;
begin
  Result := ExpandConstant('{param:RELAUNCH|0}') = '1';
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  // make sure the running app (possibly hidden in the tray) is closed before files are replaced
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM NETSniffer.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;
