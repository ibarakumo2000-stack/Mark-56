; ============================================================================
;  MARK LV — Windows installer (Inno Setup 6.3 or newer)
;  Normally compiled by scripts\build.py, which passes:
;     /DAppVersion=1.0.0 /DAppVersionInfo=1.0.0.0  /DStageDir=<build\stage>  /DOutDir=<dist>
;  and, when signing,  /DSignToolName=MarkSign
;
;  What it installs:   <stage>\runtime\   a private Python + every dependency
;                      <stage>\*          the application (main.py, core\, actions\ ...)
;                      launcher.pyw       logging + crash dialog, started by the shortcuts
;  Install location:   %LOCALAPPDATA%\Programs\MARK-LV   (per-user, NO admin prompt)
;
;  Why per-user and not Program Files: MARK LV keeps its settings (config\),
;  memory (memory\) and drop-in plugins (plugins\) beside its code and installs
;  plugin libraries on demand. A Program Files install is read-only for a normal
;  user and would break all of that.
; ============================================================================

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef AppVersionInfo
  #define AppVersionInfo "1.0.0.0"
#endif
#ifndef StageDir
  #define StageDir "..\build\stage"
#endif
#ifndef OutDir
  #define OutDir "..\dist"
#endif

#define AppName      "Jarvis"
#define AppPublisher "MARK LV"
#define AppURL       "https://www.youtube.com/@FatihMakes"
#define AppGuid      "{{6D2F0C4B-7A31-4E58-9B8D-2C5E91A7F3D4}"
#define PyExe        "{app}\runtime\pythonw.exe"
#define LauncherArg  "{app}\launcher.pyw"

[Setup]
AppId={#AppGuid}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppCopyright=Copyright (c) 2026 FatihMakes - CC BY-NC 4.0
VersionInfoVersion={#AppVersionInfo}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup

DefaultDirName={localappdata}\Programs\MARK-LV
DisableProgramGroupPage=yes
DisableDirPage=no
UsePreviousAppDir=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

OutputDir={#OutDir}
OutputBaseFilename=MARK-LV-Setup-{#AppVersion}
SetupIconFile={#StageDir}\config\jarvis.ico
UninstallDisplayIcon={app}\config\jarvis.ico
UninstallDisplayName={#AppName}
Uninstallable=yes
UninstallFilesDir={app}
LicenseFile={#StageDir}\LICENSE

Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
CloseApplications=yes
RestartApplications=no
SetupLogging=yes

; Modern wizard. On Inno Setup 6.5+ you may use "modern dynamic" to follow the Windows light/dark theme.
WizardStyle=modern
DisableWelcomePage=no
DisableReadyPage=no
DisableFinishedPage=no
ShowLanguageDialog=no
WizardSizePercent=115
WizardImageFile=assets\wizard-large.bmp,assets\wizard-large@2x.bmp
WizardSmallImageFile=assets\wizard-small.bmp,assets\wizard-small@2x.bmp

; Code signing (optional). build.py --sign-command "<cmd with $f>" turns this on.
#ifdef SignToolName
SignTool={#SignToolName}
SignedUninstaller=yes
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel1=Welcome to {#AppName}
WelcomeLabel2=Install {#AppName} {#AppVersion} on this computer.%n%nYour personal AI assistant for voice, vision, automation and productivity.%n%nEverything required to run the application is included in this installer. You do not need to install Python, VS Code or additional libraries.%n%nClick Next to continue.
LicenseAccepted=I &agree to the terms and conditions
LicenseNotAccepted=I &do not agree
SelectDirBrowseLabel=Setup will install {#AppName} in the folder below. To choose a different folder, click Browse.
FinishedHeadingLabel=Installation complete
FinishedLabel={#AppName} has been successfully installed.%n%nOn first launch it will ask for your Gemini API key.
FinishedLabelNoIcons={#AppName} has been successfully installed.

[Tasks]
Name: "startmenuicon"; Description: "Create a &Start Menu shortcut"; GroupDescription: "Shortcuts:"; Flags: checkedonce
Name: "desktopicon";   Description: "Create a &Desktop shortcut";    GroupDescription: "Shortcuts:"; Flags: unchecked
Name: "browsers";      Description: "Download browser components for web automation (about 170 MB, needs internet)"; GroupDescription: "Optional components:"

[Dirs]
Name: "{app}\config"
Name: "{app}\memory"
Name: "{app}\cache"
Name: "{app}\uploads"
Name: "{app}\plugins"

[Files]
; The staged tree already excludes secrets, personal data and dev files (see build.py).
Source: "{#StageDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{#PyExe}"; Parameters: """{#LauncherArg}"""; WorkingDir: "{app}"; IconFilename: "{app}\config\jarvis.ico"; AppUserModelID: "MarkLV.Jarvis"; Tasks: startmenuicon
Name: "{autodesktop}\{#AppName}";  Filename: "{#PyExe}"; Parameters: """{#LauncherArg}"""; WorkingDir: "{app}"; IconFilename: "{app}\config\jarvis.ico"; AppUserModelID: "MarkLV.Jarvis"; Tasks: desktopicon

[Run]
; Playwright's Chromium (web automation). Needs internet; a failure here never fails the install,
; the app retries it by itself on first use.
Filename: "{app}\runtime\python.exe"; Parameters: "-m playwright install chromium"; WorkingDir: "{app}"; StatusMsg: "Downloading browser components (one-time)..."; Flags: runhidden; Tasks: browsers
Filename: "{#PyExe}"; Parameters: """{#LauncherArg}"""; WorkingDir: "{app}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[InstallDelete]
; An upgrade replaces the runtime wholesale so stale packages cannot linger.
; config\, memory\, cache\, uploads\ and plugins\ are never touched.
Type: filesandordirs; Name: "{app}\runtime"

[UninstallDelete]
; Things created after install (never listed in the uninstall log). User data is handled in [Code].
Type: filesandordirs; Name: "{app}\runtime"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\core\__pycache__"
Type: filesandordirs; Name: "{app}\actions\__pycache__"
Type: filesandordirs; Name: "{app}\dashboard\__pycache__"
Type: filesandordirs; Name: "{app}\memory\__pycache__"
Type: filesandordirs; Name: "{app}\config\__pycache__"
Type: filesandordirs; Name: "{app}\plugins\__pycache__"

[Code]
const
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  { Inno closes applications automatically where possible. This message is only
    used if Windows reports that files are still locked. }
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    { Create writable user-data folders explicitly. }
    ForceDirectories(ExpandConstant('{app}\\config'));
    ForceDirectories(ExpandConstant('{app}\\memory'));
    ForceDirectories(ExpandConstant('{app}\\cache'));
    ForceDirectories(ExpandConstant('{app}\\uploads'));
    ForceDirectories(ExpandConstant('{app}\\plugins'));
  end;
end;



procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  WipeData: Boolean;
  Folders: array of String;
  I: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    { Things the app itself can create outside the install folder. }
    RegDeleteValue(HKEY_CURRENT_USER, RunKey, 'JARVIS_AI');      { "start with Windows" }
    DeleteFile(ExpandConstant('{userdesktop}\J.A.R.V.I.S.lnk')); { desktop shortcut the app makes }
  end;

  if CurUninstallStep = usPostUninstall then
  begin
    WipeData := False;
    if not UninstallSilent then
      WipeData := MsgBox(
        'Do you also want to delete your personal data?' + #13#10 + #13#10 +
        'This includes your saved API keys and settings, everything the assistant has ' +
        'learned about you, uploaded files, and any plugins you added.' + #13#10 + #13#10 +
        'Choose No to keep it - it will be picked up again if you reinstall.',
        mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;

    if WipeData then
    begin
      SetArrayLength(Folders, 5);
      Folders[0] := 'config';  Folders[1] := 'memory';  Folders[2] := 'cache';
      Folders[3] := 'uploads'; Folders[4] := 'plugins';
      for I := 0 to GetArrayLength(Folders) - 1 do
        DelTree(ExpandConstant('{app}\') + Folders[I], True, True, True);
      RemoveDir(ExpandConstant('{app}'));  { only succeeds if empty }
    end;
  end;
end;
