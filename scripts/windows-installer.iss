#ifndef AppVersion
  #error AppVersion must be supplied
#endif
#ifndef BundleDir
  #error BundleDir must be supplied
#endif
#ifndef OutputPath
  #define OutputPath "..\dist\installer"
#endif

[Setup]
AppId=DasKreb.MyFitnessPalMCP
AppName=MyFitnessPal MCP
AppVersion={#AppVersion}
AppPublisher=Das Kreb
AppPublisherURL=https://github.com/myke239/myfitnesspal-mcp
AppSupportURL=https://github.com/myke239/myfitnesspal-mcp/issues
DefaultDirName={localappdata}\MyFitnessPalMCP
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\assets\branding\das-kreb-logo.ico
UninstallDisplayIcon={app}\branding\das-kreb-logo.ico
OutputDir={#OutputPath}
OutputBaseFilename=myfitnesspal-mcp-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
CloseApplicationsFilter=myfitnesspal-mcp.exe,myfitnesspal-setup.exe
[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{userprograms}\MyFitnessPal MCP Setup"; Filename: "{app}\myfitnesspal-setup.exe"
[Run]
Filename: "{app}\myfitnesspal-setup.exe"; Description: "Set up MyFitnessPal MCP"; Flags: postinstall nowait skipifsilent
[UninstallRun]
Filename: "{app}\myfitnesspal-setup.exe"; Parameters: "--uninstall"; RunOnceId: "remove-mfp-codex-plugin"; Flags: runhidden waituntilterminated

[Code]
procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpWelcome) or (CurPageID = wpReady) then
    WizardForm.NextButton.Caption := 'Begin Install';
end;
