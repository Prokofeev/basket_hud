#define MyAppName "Basketball Broadcast Control"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Basketball Tools"
#define MyAppURL "https://localhost"
#define MyAppExeName "manager.exe"
#define MyAppServerBat "start_server.bat"
#define SourceReleaseDir "release\\BasketballStats"

[Setup]
AppId={{F6E8AB50-7C1E-4A0B-93A6-8E8A8F7E2C7E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=release\installer
OutputBaseFilename=BasketballBroadcastControl-Setup
SetupLogging=yes
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceReleaseDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}\Control Panel"; Filename: "{app}\{#MyAppExeName}"
Name: "{autoprograms}\{#MyAppName}\Overlay Server"; Filename: "{app}\{#MyAppServerBat}"
Name: "{autoprograms}\{#MyAppName}\Uninstall"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
var
  SourcePath: string;
begin
  SourcePath := ExpandConstant('{src}\{#SourceReleaseDir}\{#MyAppExeName}');
  if not FileExists(SourcePath) then
  begin
    MsgBox(
      'Не найден собранный релиз: ' + #13#10 + SourcePath + #13#10 + #13#10 +
      'Сначала выполните scripts\\build.ps1, затем снова запустите компиляцию setup.',
      mbError,
      MB_OK
    );
    Result := False;
    Exit;
  end;

  Result := True;
end;
