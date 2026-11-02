@echo off
rem Temp Remover - START HERE
setlocal
title Temp Remover - Deadwood Digital
set "HERE=%~dp0"
net session >nul 2>&1
if errorlevel 1 if /i not "%~1"=="elevated" (
  echo.
  echo  This works best as administrator (to clear Windows' own temp folders).
  choice /c YN /n /m " Restart as administrator now? [Y/N] "
  if not errorlevel 2 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList 'elevated' -Verb RunAs"
    exit /b 0
  )
)
set "PY="
set "PYW="
if not defined PY py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY py --version >nul 2>&1 && set "PY=py"
if not defined PY python --version >nul 2>&1 && set "PY=python"
for %%D in ("%~d0\Python" "%HERE%..\..\Python" "%HERE%..\..\..\Python") do if not defined PY if exist "%%~D\python.exe" call :useportable "%%~D"
if not defined PY (
  echo.
  echo  Python was not found on this PC and there is no portable Python at %~d0\Python.
  echo  Install Python 3.10+ from python.org ^(tick "Add python.exe to PATH"^), or run
  echo  "Install Portable Python" from the Setup folder on your Py Apps drive.
  echo.
  pause
  exit /b 1
)
%PY% -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
  echo.
  echo  This tool needs Python 3.10 or newer, and the one on this PC is older.
  echo.
  pause
  exit /b 1
)
%PY% -c "import tkinter" >nul 2>&1
if errorlevel 1 goto textmode
if not defined PYW pyw -3 -c "pass" >nul 2>&1 && set "PYW=pyw -3"
if not defined PYW pythonw -c "pass" >nul 2>&1 && set "PYW=pythonw"
if defined PYW (
  start "" %PYW% "%HERE%temp_remover.py"
  exit /b 0
)
%PY% "%HERE%temp_remover.py"
exit /b 0

:textmode
echo.
echo  TEMP REMOVER
echo  Text mode ^(this Python has no window support^). It shows a preview, then asks before it deletes.
echo.
%PY% "%HERE%temp_remover.py" --delete
echo.
pause
exit /b 0

:useportable
set PY="%~1\python.exe"
set PYW="%~1\pythonw.exe"
exit /b 0
