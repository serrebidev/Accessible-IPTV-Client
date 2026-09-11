#define MyAppName "AccessibleIPTVClient"
#define MyAppDisplayName "Accessible IPTV Client"
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppPublisher "Serrebi"
#define MyAppExeName "IPTVClient.exe"
#ifndef SourceDir
  #define SourceDir "..\dist\iptvclient"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist\release"
#endif

[Setup]
AppId={{9F1D07F7-A6F2-47E9-BDB8-C0895F3F6C6F}
AppName={#MyAppDisplayName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppDisplayName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppDisplayName}
DisableProgramGroupPage=yes
; Per-machine install into Windows' default Program Files folder. On x64 Windows,
; x64-compatible builds install under "Program Files" and 32-bit builds install
; under "Program Files (x86)". Runtime config, EPG data, schedules, logs, and
; caches are kept in %APPDATA%\AccessibleIPTVClient by options.py.
PrivilegesRequired=admin
OutputDir={#OutputDir}
OutputBaseFilename={#MyAppName}-Setup-v{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
; Select the installer language from the current Windows UI language.
; English remains the fallback for unsupported UI languages.
LanguageDetectionMethod=uilanguage
ShowLanguageDialog=no
UsePreviousLanguage=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "hungarian"; MessagesFile: "compiler:Languages\Hungarian.isl"

[CustomMessages]
; Inno Setup's stock Hungarian LaunchProgram is "Indítás %1".
; This override keeps the same meaning but uses natural Hungarian word order.
hungarian.LaunchProgram=%1 indítása

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "iptvclient.conf,epg.db,epg.db-wal,epg.db-shm,epg.db-journal,scheduled_recordings.json,iptv_cache\*,cache\*,logs\*,*.log"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "windows-installed.marker"; DestDir: "{app}"; DestName: ".windows-installed"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppDisplayName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppDisplayName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppDisplayName}}"; Flags: nowait postinstall skipifsilent
