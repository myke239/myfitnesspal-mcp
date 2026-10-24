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
CloseApplications=force
RestartApplications=no
CloseApplicationsFilter=myfitnesspal-mcp.exe
[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{userprograms}\MyFitnessPal MCP Setup"; Filename: "{app}\myfitnesspal-setup.exe"
[Run]
Filename: "{app}\myfitnesspal-setup.exe"; Description: "Set up MyFitnessPal MCP"; Flags: postinstall nowait skipifsilent
[UninstallRun]
Filename: "{app}\myfitnesspal-setup.exe"; Parameters: "--uninstall"; RunOnceId: "remove-mfp-codex-plugin"; Flags: runhidden waituntilterminated

[Code]
function VersionPart(const Version: String; PartIndex: Integer): Integer;
var
  Remaining: String;
  Separator: Integer;
  I: Integer;
begin
  Remaining := Version;
  for I := 1 to PartIndex - 1 do
  begin
    Separator := Pos('.', Remaining);
    if Separator = 0 then
    begin
      Remaining := '0';
      Break;
    end;
    Delete(Remaining, 1, Separator);
  end;
  Separator := Pos('.', Remaining);
  if Separator > 0 then
    Remaining := Copy(Remaining, 1, Separator - 1);
  Result := StrToIntDef(Remaining, 0);
end;

function IsNewerVersion(const NewVersion, OldVersion: String): Boolean;
var
  I: Integer;
  NewPart: Integer;
  OldPart: Integer;
begin
  Result := False;
  for I := 1 to 3 do
  begin
    NewPart := VersionPart(NewVersion, I);
    OldPart := VersionPart(OldVersion, I);
    if NewPart > OldPart then
    begin
      Result := True;
      Exit;
    end;
    if NewPart < OldPart then
      Exit;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  UninstallKey: String;
  PreviousVersion: String;
  UninstallCommand: String;
  UninstallExe: String;
  Separator: Integer;
  ResultCode: Integer;
begin
  Result := '';
  UninstallKey := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\DasKreb.MyFitnessPalMCP_is1';
  if not RegKeyExists(HKCU, UninstallKey) then
    Exit;
  if RegQueryStringValue(HKCU, UninstallKey, 'DisplayVersion', PreviousVersion) then
    if not IsNewerVersion('{#AppVersion}', PreviousVersion) then
      Exit;

  if not RegQueryStringValue(HKCU, UninstallKey, 'UninstallString', UninstallCommand) then
  begin
    Result := 'The previous MyFitnessPal MCP version could not be removed. Close its running server and try again.';
    Exit;
  end;

  if (Length(UninstallCommand) > 0) and (UninstallCommand[1] = '"') then
  begin
    Delete(UninstallCommand, 1, 1);
    Separator := Pos('"', UninstallCommand);
    if Separator = 0 then
    begin
      Result := 'The previous MyFitnessPal MCP installation could not be located.';
      Exit;
    end;
    UninstallExe := Copy(UninstallCommand, 1, Separator - 1);
  end
  else
  begin
    Separator := Pos(' ', UninstallCommand);
    if Separator > 0 then
      UninstallExe := Copy(UninstallCommand, 1, Separator - 1)
    else
      UninstallExe := UninstallCommand;
  end;

  if (ExtractFileName(UninstallExe) = '') or
     (Pos('unins', Lowercase(ExtractFileName(UninstallExe))) <> 1) or
     (Lowercase(ExtractFileExt(UninstallExe)) <> '.exe') or
     (not FileExists(UninstallExe)) then
  begin
    Result := 'The previous MyFitnessPal MCP installation could not be removed. Close its running server and try again.';
    Exit;
  end;

  if not Exec(UninstallExe, '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /NOCLOSEAPPLICATIONS',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    Result := 'The previous MyFitnessPal MCP version could not be removed. Close its running server and try again.';
    Exit;
  end;
  if ResultCode <> 0 then
    Result := 'The previous MyFitnessPal MCP version could not be removed. Close its running server and try again.';
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpWelcome) or (CurPageID = wpReady) then
    WizardForm.NextButton.Caption := 'Begin Install';
end;
