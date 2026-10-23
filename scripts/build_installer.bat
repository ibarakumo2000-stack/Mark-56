@echo off
rem One-command build:  scripts\build_installer.bat   ->   dist\MARK-LV-Setup-<version>.exe
rem Extra options are passed through, e.g.:  scripts\build_installer.bat --version 1.1.0
setlocal
cd /d "%~dp0.."
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python 3 is required to RUN THE BUILD SCRIPT ^(end users never need it^). Get it from python.org.
  exit /b 1
)
%PY% scripts\build.py %*
exit /b %errorlevel%
