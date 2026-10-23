@echo off
setlocal
cd /d "%~dp0"
echo.
echo ============================================================
echo                 MARK LV INSTALLER BUILDER
echo ============================================================
echo.
echo This builds the standalone Windows installer.
echo Requirements on this build PC:
echo   - Windows 10/11 x64
echo   - Python 3.9+
echo   - Inno Setup 6.3+
echo   - Internet access for the first runtime build
echo.
call scripts\build_installer.bat %*
if errorlevel 1 (
  echo.
  echo BUILD FAILED.
  pause
  exit /b 1
)
echo.
echo BUILD COMPLETE.
echo Check the dist folder for MARK-LV-Setup-*.exe
pause
