; Build the application with build-windows.ps1, then compile this with Inno Setup 6.
#define AppVersion "0.2.0"
[Setup]
AppId={{C113C089-4215-44DA-BE58-50E9C4ED56A8}
AppName=GitPush Agent
AppVersion={#AppVersion}
AppPublisher=GitPush Agent
DefaultDirName={localappdata}\Programs\GitPushAgent
DefaultGroupName=GitPush Agent
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=GitPushAgent-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\GitPushAgent.exe
CloseApplications=yes
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
[Files]
Source: "..\dist\GitPushAgent\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\GitPush Agent"; Filename: "{app}\GitPushAgent.exe"
Name: "{autodesktop}\GitPush Agent"; Filename: "{app}\GitPushAgent.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\GitPushAgent.exe"; Description: "Open GitPush Agent setup"; Flags: nowait postinstall skipifsilent
[Registry]
; Remove the optional app-owned startup entry on uninstall, without deleting user data.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "GitPushAgent"; Flags: uninsdeletevalue
