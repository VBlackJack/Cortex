; Copyright 2026 Julien Bombled
;
; Licensed under the Apache License, Version 2.0 (the "License");
; you may not use this file except in compliance with the License.
; You may obtain a copy of the License at
;
;     http://www.apache.org/licenses/LICENSE-2.0
;
; Unless required by applicable law or agreed to in writing, software
; distributed under the License is distributed on an "AS IS" BASIS,
; WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
; See the License for the specific language governing permissions and
; limitations under the License.

#ifndef AppVersion
  #error AppVersion must be provided with ISCC /DAppVersion=<version>
#endif

[Setup]
AppId=Cortex
AppName=Cortex
AppPublisher=Julien Bombled
AppVersion={#AppVersion}
AppVerName=Cortex {#AppVersion}
DefaultDirName={localappdata}\Programs\Cortex
DefaultGroupName=Cortex
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesEnvironment=yes
UninstallDisplayName=Cortex
UninstallDisplayIcon={app}\cortex.exe
OutputDir=..\..\dist-installer
OutputBaseFilename=Cortex-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
#ifdef InstallerSignTool
SignTool={#InstallerSignTool}
SignedUninstaller=yes
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[CustomMessages]
english.KBPageCaption=Knowledge base folder
english.KBPageDescription=Choose where Cortex will read your documents.
english.KBPageSubCaption=You can start with an empty folder and add documents later.
english.IndexNow=Index this folder now
english.SetupFailed=Cortex was installed, but automatic setup failed. Run Cortex Doctor from the Start menu after correcting the problem. Setup will return a failure exit code.
english.PathFailed=Cortex could not add its application folder to your user PATH.
english.EnvironmentFailed=Cortex could not pass the selected knowledge base folder to the setup process.
english.DirectoryFailed=Cortex could not create the selected knowledge base folder:
english.UnregisterFailed=Cortex could not remove every MCP client entry. The uninstall will continue; review the client configurations manually.
french.KBPageCaption=Dossier de base de connaissances
french.KBPageDescription=Choisissez le dossier dans lequel Cortex lira vos documents.
french.KBPageSubCaption=Vous pouvez commencer avec un dossier vide et ajouter des documents plus tard.
french.IndexNow=Indexer ce dossier maintenant
french.SetupFailed=Cortex a ete installe, mais la configuration automatique a echoue. Lancez Cortex Doctor depuis le menu Demarrer apres avoir corrige le probleme. L'installeur retournera un code d'echec.
french.PathFailed=Cortex n'a pas pu ajouter son dossier d'application au PATH utilisateur.
french.EnvironmentFailed=Cortex n'a pas pu transmettre le dossier de base de connaissances au processus de configuration.
french.DirectoryFailed=Cortex n'a pas pu creer le dossier de base de connaissances selectionne :
french.UnregisterFailed=Cortex n'a pas pu retirer toutes les entrees des clients MCP. La desinstallation continue ; verifiez manuellement les configurations clientes.

[Files]
Source: "..\..\dist\cortex.exe"; DestDir: "{app}"; DestName: "cortex.exe"; Flags: ignoreversion

[Icons]
Name: "{group}\Cortex Doctor"; Filename: "{cmd}"; Parameters: "/k """"{app}\cortex.exe"" doctor"""
Name: "{group}\Cortex Sync"; Filename: "{cmd}"; Parameters: "/k """"{app}\cortex.exe"" sync"""

[Code]
var
  KnowledgeBasePage: TInputDirWizardPage;
  IndexNowCheckBox: TNewCheckBox;
  KnowledgeBasePath: String;
  SetupFailed: Boolean;

function SetEnvironmentVariable(lpName, lpValue: String): BOOL;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

function CommandLineSwitchPresent(const Name: String): Boolean;
var
  Index: Integer;
begin
  Result := False;
  for Index := 1 to ParamCount do
  begin
    if CompareText(ParamStr(Index), '/' + Name) = 0 then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function CommandLineValue(const Name: String): String;
begin
  Result := Trim(ExpandConstant('{param:' + Name + '|}'));
end;

function SelectedKnowledgeBasePath: String;
begin
  if WizardSilent then
    Result := CommandLineValue('KBPATH')
  else
    Result := Trim(KnowledgeBasePage.Values[0]);
  if Result = '' then
    Result := ExpandConstant('{userdocs}\Cortex-KB');
end;

function ShouldIndexNow: Boolean;
begin
  if WizardSilent then
    Result := CommandLineSwitchPresent('INDEX')
  else
    Result := IndexNowCheckBox.Checked;
end;

procedure InitializeWizard;
var
  InitialPath: String;
begin
  KnowledgeBasePage := CreateInputDirPage(
    wpSelectDir,
    CustomMessage('KBPageCaption'),
    CustomMessage('KBPageDescription'),
    CustomMessage('KBPageSubCaption'),
    False,
    ''
  );
  KnowledgeBasePage.Add('');
  InitialPath := CommandLineValue('KBPATH');
  if InitialPath = '' then
    InitialPath := ExpandConstant('{userdocs}\Cortex-KB');
  KnowledgeBasePage.Values[0] := InitialPath;

  IndexNowCheckBox := TNewCheckBox.Create(KnowledgeBasePage);
  IndexNowCheckBox.Parent := KnowledgeBasePage.Surface;
  IndexNowCheckBox.Caption := CustomMessage('IndexNow');
  IndexNowCheckBox.Checked := True;
  IndexNowCheckBox.Top :=
    KnowledgeBasePage.Edits[0].Top + KnowledgeBasePage.Edits[0].Height + ScaleY(16);
  IndexNowCheckBox.Left := KnowledgeBasePage.Edits[0].Left;
  IndexNowCheckBox.Width := KnowledgeBasePage.Edits[0].Width;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := WizardSilent and (PageID = KnowledgeBasePage.ID);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  KnowledgeBasePath := SelectedKnowledgeBasePath;
  if not DirExists(KnowledgeBasePath) and not ForceDirectories(KnowledgeBasePath) then
    Result := CustomMessage('DirectoryFailed') + #13#10 + KnowledgeBasePath;
end;

function NormalizePathEntry(const Value: String): String;
begin
  Result := Trim(Value);
  if (Length(Result) >= 2) and (Result[1] = '"') and
     (Result[Length(Result)] = '"') then
  begin
    Delete(Result, Length(Result), 1);
    Delete(Result, 1, 1);
  end;
  StringChangeEx(Result, '/', '\', True);
  while (Length(Result) > 3) and (Result[Length(Result)] = '\') do
    Delete(Result, Length(Result), 1);
end;

function UserPathContains(const UserPath, Entry: String): Boolean;
var
  Remaining: String;
  Part: String;
  SeparatorPosition: Integer;
begin
  Result := False;
  Remaining := UserPath;
  while True do
  begin
    SeparatorPosition := Pos(';', Remaining);
    if SeparatorPosition = 0 then
    begin
      Part := Remaining;
      Remaining := '';
    end
    else
    begin
      Part := Copy(Remaining, 1, SeparatorPosition - 1);
      Delete(Remaining, 1, SeparatorPosition);
    end;
    if CompareText(NormalizePathEntry(Part), NormalizePathEntry(Entry)) = 0 then
    begin
      Result := True;
      Exit;
    end;
    if SeparatorPosition = 0 then
      Exit;
  end;
end;

function AddAppToUserPath: Boolean;
var
  CurrentPath: String;
  AppPath: String;
  NewPath: String;
begin
  AppPath := ExpandConstant('{app}');
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', CurrentPath) then
    CurrentPath := '';
  if UserPathContains(CurrentPath, AppPath) then
  begin
    Result := True;
    Exit;
  end;
  if CurrentPath = '' then
    NewPath := AppPath
  else if CurrentPath[Length(CurrentPath)] = ';' then
    NewPath := CurrentPath + AppPath
  else
    NewPath := CurrentPath + ';' + AppPath;
  Result := RegWriteExpandStringValue(HKCU, 'Environment', 'Path', NewPath);
  if Result then
    Log('Added Cortex application directory to the user PATH.');
end;

function PathWithoutEntry(
  const UserPath, Entry: String;
  var Removed: Boolean
): String;
var
  Remaining: String;
  Part: String;
  SeparatorPosition: Integer;
  Finished: Boolean;
  WrotePart: Boolean;
begin
  Result := '';
  Removed := False;
  Remaining := UserPath;
  Finished := False;
  WrotePart := False;
  while not Finished do
  begin
    SeparatorPosition := Pos(';', Remaining);
    if SeparatorPosition = 0 then
    begin
      Part := Remaining;
      Remaining := '';
      Finished := True;
    end
    else
    begin
      Part := Copy(Remaining, 1, SeparatorPosition - 1);
      Delete(Remaining, 1, SeparatorPosition);
    end;

    if CompareText(NormalizePathEntry(Part), NormalizePathEntry(Entry)) = 0 then
      Removed := True
    else
    begin
      if WrotePart then
        Result := Result + ';';
      Result := Result + Part;
      WrotePart := True;
    end;
  end;
end;

procedure RemoveAppFromUserPath;
var
  CurrentPath: String;
  NewPath: String;
  Removed: Boolean;
begin
  if not RegQueryStringValue(HKCU, 'Environment', 'Path', CurrentPath) then
    Exit;
  NewPath := PathWithoutEntry(CurrentPath, ExpandConstant('{app}'), Removed);
  if not Removed then
    Exit;
  if NewPath = '' then
    RegDeleteValue(HKCU, 'Environment', 'Path')
  else
    RegWriteExpandStringValue(HKCU, 'Environment', 'Path', NewPath);
  Log('Removed Cortex application directory from the user PATH.');
end;

procedure MarkSetupFailure(const MessageText: String);
begin
  SetupFailed := True;
  Log('Cortex post-install setup failed: ' + MessageText);
  SuppressibleMsgBox(
    MessageText + #13#10#13#10 + CustomMessage('SetupFailed'),
    mbError,
    MB_OK,
    IDOK
  );
end;

procedure RunCortexSetup;
var
  Parameters: String;
  ResultCode: Integer;
begin
  if not AddAppToUserPath then
  begin
    MarkSetupFailure(CustomMessage('PathFailed'));
    Exit;
  end;
  if not SetEnvironmentVariable('CORTEX_KB_PATH', KnowledgeBasePath) then
  begin
    MarkSetupFailure(CustomMessage('EnvironmentFailed'));
    Exit;
  end;

  Parameters := 'setup --yes --clients all';
  if not ShouldIndexNow then
    Parameters := Parameters + ' --no-index';
  if not Exec(
    ExpandConstant('{app}\cortex.exe'),
    Parameters,
    ExpandConstant('{app}'),
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode
  ) then
    MarkSetupFailure('Could not start cortex.exe.')
  else if ResultCode <> 0 then
    MarkSetupFailure('cortex setup returned exit code ' + IntToStr(ResultCode) + '.');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    RunCortexSetup;
end;

function GetCustomSetupExitCode: Integer;
begin
  if SetupFailed then
    Result := 20
  else
    Result := 0;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ExecutablePath: String;
  ResultCode: Integer;
begin
  if CurUninstallStep <> usUninstall then
    Exit;

  ExecutablePath := ExpandConstant('{app}\cortex.exe');
  if FileExists(ExecutablePath) then
  begin
    if not Exec(
      ExecutablePath,
      'unregister --yes --clients all',
      ExpandConstant('{app}'),
      SW_HIDE,
      ewWaitUntilTerminated,
      ResultCode
    ) then
    begin
      Log('Cortex client unregistration failed during uninstall.');
      SuppressibleMsgBox(
        CustomMessage('UnregisterFailed'),
        mbError,
        MB_OK,
        IDOK
      );
    end
    else if ResultCode <> 0 then
    begin
      Log(
        'Cortex client unregistration returned exit code ' +
        IntToStr(ResultCode) + ' during uninstall.'
      );
      SuppressibleMsgBox(
        CustomMessage('UnregisterFailed'),
        mbError,
        MB_OK,
        IDOK
      );
    end;
  end;
  RemoveAppFromUserPath;
end;
