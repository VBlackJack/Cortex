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
#ifndef PayloadVersionVerified
  #error Compile through build_installer.py to validate dist/cortex.exe first
#endif
#if !SameStr(AppVersion, PayloadVersionVerified)
  #error AppVersion does not match the validated dist/cortex.exe version
#endif
#ifndef CompanionPayloadDir
  #error CompanionPayloadDir must be provided by build_installer.py
#endif
#ifndef CompanionPayloadVersionVerified
  #error Compile through build_installer.py to validate CortexCompanion.exe first
#endif
#if !SameStr(AppVersion, CompanionPayloadVersionVerified)
  #error AppVersion does not match the validated CortexCompanion.exe version
#endif
#ifndef ConverterPayloadDir
  #error ConverterPayloadDir must be provided by build_installer.py
#endif
#ifndef ConverterPayloadVerified
  #error Compile through build_installer.py to validate the Confluence converter probe
#endif

; Direct ISCC compilation is intentionally blocked above. The shared local and
; CI wrapper validates dist/cortex.exe --version before supplying the proof.

#ifndef ModelPayloadDir
  #error ModelPayloadDir must be provided with ISCC /DModelPayloadDir=<path>
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
CloseApplications=force
CloseApplicationsFilter=cortex.exe,CortexCompanion.exe
#ifdef InstallerSignTool
SignTool={#InstallerSignTool}
SignedUninstaller=yes
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[CustomMessages]
english.ReinstallCaption=Existing Cortex configuration
english.ReinstallDescription=Choose what this installation should do with your current setup.
english.ReinstallSubCaption=Keep preserves your configuration and index. Reset deletes generated Cortex state, then applies the folder and indexing choices on the next pages.
english.KeepConfig=Keep my current Cortex configuration (recommended)
english.ResetConfig=Reset configuration and rebuild the index from scratch
english.KBPageCaption=Knowledge base folder
english.KBPageDescription=Choose where Cortex will read your documents.
english.KBPageSubCaption=You can start with an empty folder and add documents later.
english.IndexNow=Index this folder now
english.IndexModeCaption=Indexing mode
english.IndexModeDescription=Choose how Cortex should read this folder.
english.IndexModeSubCaption=Recommended: everything is searchable automatically. Advanced: only named section folders are indexed.
english.WholeFolderMode=Index everything in this folder (recommended)
english.SectionsMode=Organize into sections (advanced)
english.SectionsCaption=Section folders
english.SectionsDescription=Choose the folders Cortex should create and index.
english.SectionsHelp=knowledge: reference documents; projects: working files; notes: free-form notes. You may edit this list.
english.SectionsList=Section folders (comma-separated):
english.IndexModeFailed=Index mode must be whole or sections.
english.SectionsFailed=Enter at least one comma-separated section folder.
english.SetupFailed=Cortex was installed, but automatic setup failed. Run Cortex Doctor from the Start menu after correcting the problem. Setup will return a failure exit code.
english.PathFailed=Cortex could not add its application folder to your user PATH.
english.EnvironmentFailed=Cortex could not pass the selected knowledge base folder to the setup process.
english.DirectoryFailed=Cortex could not create the selected knowledge base folder:
english.ResetFailed=Cortex could not reset its configuration and generated index. Close every AI application using Cortex, then run the installer again.
english.UnregisterFailed=Cortex could not remove every MCP client entry. The uninstall will continue; review the client configurations manually.
english.CompanionCleanupFailed=Cortex Companion could not safely remove its owned ingestion task. The uninstall will continue; review Task Scheduler manually.
french.ReinstallCaption=Configuration Cortex existante
french.ReinstallDescription=Choisissez ce que cette installation doit faire de votre configuration actuelle.
french.ReinstallSubCaption=Garder conserve la configuration et l'index. Réinitialiser efface les données Cortex générées, puis applique le dossier et le mode choisis aux pages suivantes.
french.KeepConfig=Garder ma configuration Cortex actuelle (recommandé)
french.ResetConfig=Réinitialiser la configuration et reconstruire l'index
french.KBPageCaption=Dossier de base de connaissances
french.KBPageDescription=Choisissez le dossier dans lequel Cortex lira vos documents.
french.KBPageSubCaption=Vous pouvez commencer avec un dossier vide et ajouter des documents plus tard.
french.IndexNow=Indexer ce dossier maintenant
french.IndexModeCaption=Mode d'indexation
french.IndexModeDescription=Choisissez comment Cortex doit lire ce dossier.
french.IndexModeSubCaption=Recommandé : tout devient cherchable automatiquement. Avancé : seuls les dossiers de sections nommés sont indexés.
french.WholeFolderMode=Tout indexer dans ce dossier (recommandé)
french.SectionsMode=Organiser en sections (avancé)
french.SectionsCaption=Dossiers de sections
french.SectionsDescription=Choisissez les dossiers que Cortex doit créer et indexer.
french.SectionsHelp=knowledge : documents de référence ; projects : dossiers de travail ; notes : notes libres. Vous pouvez modifier cette liste.
french.SectionsList=Dossiers de sections (séparés par des virgules) :
french.IndexModeFailed=Le mode d'indexation doit être whole ou sections.
french.SectionsFailed=Indiquez au moins un dossier de section, séparé par des virgules.
french.SetupFailed=Cortex a été installé, mais la configuration automatique a échoué. Lancez Cortex Doctor depuis le menu Démarrer après avoir corrigé le problème. L'installeur retournera un code d'échec.
french.PathFailed=Cortex n'a pas pu ajouter son dossier d'application au PATH utilisateur.
french.EnvironmentFailed=Cortex n'a pas pu transmettre le dossier de base de connaissances au processus de configuration.
french.DirectoryFailed=Cortex n'a pas pu créer le dossier de base de connaissances sélectionné :
french.ResetFailed=Cortex n'a pas pu réinitialiser sa configuration et son index généré. Fermez toutes les applications IA utilisant Cortex, puis relancez l'installeur.
french.UnregisterFailed=Cortex n'a pas pu retirer toutes les entrées des clients MCP. La désinstallation continue ; vérifiez manuellement les configurations clientes.
french.CompanionCleanupFailed=Cortex Companion n'a pas pu retirer de façon sûre sa tâche d'ingestion détenue. La désinstallation continue ; vérifiez manuellement le Planificateur de tâches.

[Files]
Source: "..\..\dist\cortex.exe"; DestDir: "{app}"; DestName: "cortex.exe"; Flags: ignoreversion
Source: "..\..\dist\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#CompanionPayloadDir}\*"; DestDir: "{app}\Companion"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ConverterPayloadDir}\*"; DestDir: "{app}\Converters"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ModelPayloadDir}\*"; DestDir: "{localappdata}\Cortex\models"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\LICENSE"; DestDir: "{localappdata}\Cortex\models\licenses"; DestName: "Apache-2.0.txt"; Flags: ignoreversion
Source: "..\..\THIRD_PARTY_NOTICES.md"; DestDir: "{localappdata}\Cortex\models\licenses"; Flags: ignoreversion

[Icons]
Name: "{group}\Cortex Companion"; Filename: "{app}\Companion\CortexCompanion.exe"; WorkingDir: "{app}\Companion"
Name: "{group}\Cortex Doctor"; Filename: "{cmd}"; Parameters: "/k """"{app}\cortex.exe"" doctor"""
Name: "{group}\Cortex Sync"; Filename: "{cmd}"; Parameters: "/k """"{app}\cortex.exe"" sync"""

[Run]
Filename: "{app}\Companion\CortexCompanion.exe"; Description: "{cm:LaunchProgram,Cortex Companion}"; WorkingDir: "{app}\Companion"; Flags: nowait postinstall skipifsilent; Check: ShouldLaunchCompanion

[Code]
var
  ReinstallPage: TInputOptionWizardPage;
  KnowledgeBasePage: TInputDirWizardPage;
  IndexNowCheckBox: TNewCheckBox;
  IndexModePage: TInputOptionWizardPage;
  SectionsPage: TInputQueryWizardPage;
  KnowledgeBasePath: String;
  ExistingConfigDetected: Boolean;
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

function ResetConfigurationRequested: Boolean;
begin
  if CommandLineSwitchPresent('RESETCONFIG') then
    Result := True
  else if WizardSilent then
    Result := False
  else
    Result := ExistingConfigDetected and (ReinstallPage.SelectedValueIndex = 1);
end;

function KeepExistingConfiguration: Boolean;
begin
  Result := ExistingConfigDetected and not ResetConfigurationRequested;
end;

function ShouldIndexNow: Boolean;
begin
  if WizardSilent then
    Result := CommandLineSwitchPresent('INDEX')
  else
    Result := IndexNowCheckBox.Checked;
end;

function SelectedIndexMode: String;
begin
  if WizardSilent then
    Result := Lowercase(CommandLineValue('INDEXMODE'))
  else if IndexModePage.SelectedValueIndex = 1 then
    Result := 'sections'
  else
    Result := 'whole';
  if Result = '' then
    Result := 'whole';
end;

function SelectedSections: String;
begin
  if WizardSilent then
  begin
    Result := CommandLineValue('SECTIONS');
    if Result = '' then
      Result := 'knowledge,projects,notes';
  end
  else
    Result := Trim(SectionsPage.Values[0]);
end;

procedure InitializeWizard;
var
  InitialPath: String;
begin
  ExistingConfigDetected := FileExists(
    ExpandConstant('{userappdata}\Cortex\config.toml')
  );
  ReinstallPage := CreateInputOptionPage(
    wpWelcome,
    CustomMessage('ReinstallCaption'),
    CustomMessage('ReinstallDescription'),
    CustomMessage('ReinstallSubCaption'),
    True,
    False
  );
  ReinstallPage.Add(CustomMessage('KeepConfig'));
  ReinstallPage.Add(CustomMessage('ResetConfig'));
  if CommandLineSwitchPresent('RESETCONFIG') then
    ReinstallPage.SelectedValueIndex := 1
  else
    ReinstallPage.SelectedValueIndex := 0;

  KnowledgeBasePage := CreateInputDirPage(
    ReinstallPage.ID,
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

  IndexModePage := CreateInputOptionPage(
    KnowledgeBasePage.ID,
    CustomMessage('IndexModeCaption'),
    CustomMessage('IndexModeDescription'),
    CustomMessage('IndexModeSubCaption'),
    True,
    False
  );
  IndexModePage.Add(CustomMessage('WholeFolderMode'));
  IndexModePage.Add(CustomMessage('SectionsMode'));
  IndexModePage.SelectedValueIndex := 0;

  SectionsPage := CreateInputQueryPage(
    IndexModePage.ID,
    CustomMessage('SectionsCaption'),
    CustomMessage('SectionsDescription'),
    CustomMessage('SectionsHelp')
  );
  SectionsPage.Add(CustomMessage('SectionsList'), False);
  SectionsPage.Values[0] := 'knowledge,projects,notes';
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  if WizardSilent then
    Result :=
      (PageID = ReinstallPage.ID) or
      (PageID = KnowledgeBasePage.ID) or
      (PageID = IndexModePage.ID) or
      (PageID = SectionsPage.ID)
  else if (PageID = ReinstallPage.ID) then
    Result := not ExistingConfigDetected
  else if KeepExistingConfiguration then
    Result :=
      (PageID = KnowledgeBasePage.ID) or
      (PageID = IndexModePage.ID) or
      (PageID = SectionsPage.ID)
  else
    Result :=
      (PageID = SectionsPage.ID) and
      (IndexModePage.SelectedValueIndex = 0);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if KeepExistingConfiguration then
  begin
    KnowledgeBasePath := '';
    Exit;
  end;
  KnowledgeBasePath := SelectedKnowledgeBasePath;
  if (SelectedIndexMode <> 'whole') and (SelectedIndexMode <> 'sections') then
  begin
    Result := CustomMessage('IndexModeFailed');
    Exit;
  end;
  if (SelectedIndexMode = 'sections') and (Trim(SelectedSections) = '') then
  begin
    Result := CustomMessage('SectionsFailed');
    Exit;
  end;
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
  IndexMode: String;
  Parameters: String;
  ResetConfiguration: Boolean;
  ResultCode: Integer;
begin
  if not AddAppToUserPath then
  begin
    MarkSetupFailure(CustomMessage('PathFailed'));
    Exit;
  end;
  ResetConfiguration := ResetConfigurationRequested;
  if not KeepExistingConfiguration then
  begin
    if not SetEnvironmentVariable('CORTEX_KB_PATH', KnowledgeBasePath) then
    begin
      MarkSetupFailure(CustomMessage('EnvironmentFailed'));
      Exit;
    end;
    IndexMode := SelectedIndexMode;
    if not SetEnvironmentVariable('CORTEX_INDEX_MODE', IndexMode) then
    begin
      MarkSetupFailure(CustomMessage('EnvironmentFailed'));
      Exit;
    end;
    if IndexMode = 'sections' then
    begin
      if not SetEnvironmentVariable('CORTEX_INDEX_SECTIONS', SelectedSections) then
      begin
        MarkSetupFailure(CustomMessage('EnvironmentFailed'));
        Exit;
      end;
    end
    else
      SetEnvironmentVariable('CORTEX_INDEX_SECTIONS', '');
  end;

  Parameters := 'setup --yes --clients all';
  if ResetConfiguration then
    Parameters := Parameters + ' --reset';
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
  begin
    if ResetConfiguration then
      MarkSetupFailure(CustomMessage('ResetFailed'))
    else
      MarkSetupFailure('cortex setup returned exit code ' + IntToStr(ResultCode) + '.');
  end;
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

function ShouldLaunchCompanion: Boolean;
begin
  Result := not SetupFailed;
end;

procedure ReportCompanionCleanupFailure(const Details: String);
begin
  Log('Cortex Companion uninstall cleanup failed: ' + Details);
  SuppressibleMsgBox(
    CustomMessage('CompanionCleanupFailed'),
    mbError,
    MB_OK,
    IDOK
  );
end;

procedure RunCompanionUninstallCleanup;
var
  CompanionPath: String;
  CleanupOutput: TExecOutput;
  CleanupStatus: String;
  Launched: Boolean;
  ResultCode: Integer;
begin
  CompanionPath := ExpandConstant('{app}\Companion\CortexCompanion.exe');
  if not FileExists(CompanionPath) then
  begin
    ReportCompanionCleanupFailure('CortexCompanion.exe is missing.');
    Exit;
  end;

  Launched := False;
  ResultCode := -1;
  try
    Launched := ExecAndCaptureOutput(
      CompanionPath,
      '--uninstall-cleanup',
      ExpandConstant('{app}\Companion'),
      SW_SHOWNORMAL,
      ewWaitUntilTerminated,
      ResultCode,
      CleanupOutput
    );
  except
    Log('Cortex Companion cleanup capture failed: ' + GetExceptionMessage);
  end;

  if not Launched then
  begin
    ReportCompanionCleanupFailure(
      'process launch failed with code ' + IntToStr(ResultCode) + '.'
    );
    Exit;
  end;
  if CleanupOutput.Error then
  begin
    ReportCompanionCleanupFailure('stdout/stderr capture failed.');
    Exit;
  end;
  if GetArrayLength(CleanupOutput.StdErr) <> 0 then
  begin
    ReportCompanionCleanupFailure('unexpected stderr output.');
    Exit;
  end;
  if GetArrayLength(CleanupOutput.StdOut) <> 1 then
  begin
    ReportCompanionCleanupFailure('stdout was not exactly one status line.');
    Exit;
  end;

  CleanupStatus := CleanupOutput.StdOut[0];
  if (ResultCode = 0) and
     ((CleanupStatus = 'cleanup=deleted') or
      (CleanupStatus = 'cleanup=absent') or
      (CleanupStatus = 'cleanup=foreign-preserved')) then
  begin
    Log('Cortex Companion uninstall cleanup: ' + CleanupStatus);
    Exit;
  end;

  if (ResultCode = 1) and
     ((CleanupStatus = 'cleanup=failed') or
      (CleanupStatus = 'cleanup=cancelled')) then
  begin
    ReportCompanionCleanupFailure(CleanupStatus + '.');
    Exit;
  end;

  ReportCompanionCleanupFailure(
    'unexpected exit/status pair: exit=' + IntToStr(ResultCode) +
    ', stdout=' + CleanupStatus + '.'
  );
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ExecutablePath: String;
  ResultCode: Integer;
begin
  if CurUninstallStep <> usUninstall then
    Exit;

  RunCompanionUninstallCleanup;

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
