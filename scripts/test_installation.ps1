<#
.SYNOPSIS
  Automated install -> launch -> uninstall check for the MARK LV installer.

.DESCRIPTION
  Run this on a Windows machine that is NOT your dev box, ideally a fresh VM
  (Windows Sandbox or Hyper-V checkpoint) with no Python / VS Code installed.
  It performs a silent install into a temp folder, verifies the files, shortcuts
  and Apps-list entry, launches the app for a while and scans its log for import
  errors, then silently uninstalls and verifies removal.

  It cannot test the microphone, camera or Gemini features - see the manual
  checklist in INSTALLER_BUILD.md for those.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\test_installation.ps1 -Installer dist\MARK-LV-Setup-1.0.0.exe
#>
param(
  [Parameter(Mandatory)][string]$Installer,
  [string]$InstallDir = (Join-Path $env:TEMP "MarkLV-test"),
  [int]$RunSeconds = 30
)
$ErrorActionPreference = "Stop"
$script:fail = @()
function Check([bool]$ok, [string]$msg) {
  if ($ok) { Write-Host "  ok   $msg" -ForegroundColor Green }
  else     { Write-Host "  FAIL $msg" -ForegroundColor Red; $script:fail += $msg }
}

$Installer = (Resolve-Path $Installer).Path
$uninstKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{6D2F0C4B-7A31-4E58-9B8D-2C5E91A7F3D4}_is1'
$startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\MARK LV.lnk'
$desktop   = Join-Path ([Environment]::GetFolderPath('Desktop')) 'MARK LV.lnk'
$logFile   = Join-Path $env:LOCALAPPDATA 'MARK-LV\logs\mark-lv.log'

Write-Host "`n[0] environment"
$py = Get-Command python -ErrorAction SilentlyContinue
if ($py) { Write-Host "  WARN Python is installed on this machine ($($py.Source)); use a clean VM for a true clean-machine test." -ForegroundColor Yellow }
else     { Write-Host "  ok   no Python on PATH" -ForegroundColor Green }

Write-Host "`n[1] silent install -> $InstallDir"
if (Test-Path $InstallDir) { Remove-Item $InstallDir -Recurse -Force }
$setupLog = Join-Path $env:TEMP 'marklv-setup.log'
$p = Start-Process $Installer -Wait -PassThru -ArgumentList @(
  '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=`"$InstallDir`"",
  '/TASKS="startmenuicon,desktopicon"', "/LOG=`"$setupLog`"")
Check ($p.ExitCode -eq 0) "installer exit code 0 (was $($p.ExitCode); log: $setupLog)"

Write-Host "`n[2] installed files"
foreach ($f in 'runtime\pythonw.exe','runtime\python.exe','launcher.pyw','main.py','ui.py','VERSION','LICENSE',
               'core\prompt.txt','core\face_model.obj','config\jarvis.ico') {
  Check (Test-Path (Join-Path $InstallDir $f)) $f
}
Check (-not (Test-Path (Join-Path $InstallDir 'config\api_keys.json'))) "no api_keys.json shipped"
Check (-not (Test-Path (Join-Path $InstallDir 'config\certs')))         "no private certificates shipped"
Check (-not (Test-Path (Join-Path $InstallDir 'memory\long_term.json'))) "no personal memory shipped"

Write-Host "`n[3] Windows integration"
Check (Test-Path $startMenu) "Start Menu shortcut"
Check (Test-Path $desktop)   "Desktop shortcut"
Check (Test-Path -LiteralPath $uninstKey) "listed in Settings > Apps (uninstall registry key)"
Check (Test-Path (Join-Path $InstallDir 'unins000.exe')) "uninstaller present"

Write-Host "`n[4] launch for $RunSeconds s"
$before = if (Test-Path $logFile) { (Get-Item $logFile).Length } else { 0 }
$app = Start-Process (Join-Path $InstallDir 'runtime\pythonw.exe') -PassThru `
        -ArgumentList "`"$(Join-Path $InstallDir 'launcher.pyw')`"" -WorkingDirectory $InstallDir
Start-Sleep -Seconds $RunSeconds
Check (-not $app.HasExited) "app still running after $RunSeconds s (exit code if it died: $($app.ExitCode))"
Check (Test-Path $logFile) "log written to $logFile"
if (Test-Path $logFile) {
  $fs = [IO.File]::Open($logFile,'Open','Read','ReadWrite'); $null = $fs.Seek($before,'Begin')
  $new = (New-Object IO.StreamReader $fs).ReadToEnd(); $fs.Close()
  foreach ($bad in 'ModuleNotFoundError','ImportError','DLL load failed','FileNotFoundError','Traceback') {
    Check ($new -notmatch [regex]::Escape($bad)) "log has no '$bad'"
  }
}
if (-not $app.HasExited) { Stop-Process -Id $app.Id -Force }
Start-Sleep -Seconds 2

Write-Host "`n[5] silent uninstall"
$u = Start-Process (Join-Path $InstallDir 'unins000.exe') -Wait -PassThru -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'
Check ($u.ExitCode -eq 0) "uninstaller exit code 0 (was $($u.ExitCode))"
Start-Sleep -Seconds 3   # the uninstaller finishes its own cleanup in a detached copy
Check (-not (Test-Path (Join-Path $InstallDir 'runtime'))) "runtime removed"
Check (-not (Test-Path (Join-Path $InstallDir 'main.py')))  "application files removed"
Check (-not (Test-Path $startMenu)) "Start Menu shortcut removed"
Check (-not (Test-Path $desktop))   "Desktop shortcut removed"
Check (-not (Test-Path -LiteralPath $uninstKey)) "removed from Settings > Apps"
Write-Host "  note silent uninstall keeps user data (config, memory, plugins) by design" -ForegroundColor DarkGray

Write-Host ""
if ($script:fail.Count) { Write-Host "FAILED: $($script:fail.Count) check(s)" -ForegroundColor Red; $script:fail | ForEach-Object { "  - $_" }; exit 1 }
Write-Host "ALL CHECKS PASSED" -ForegroundColor Green
