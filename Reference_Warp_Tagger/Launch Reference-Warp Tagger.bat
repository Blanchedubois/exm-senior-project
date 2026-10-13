@echo off
REM ============================================================================
REM  Double-click to install the required libraries (first run) and open the
REM  Reference-Warp Tagger. Windows version of "Launch Reference-Warp Tagger.command".
REM
REM  IMPORTANT: this project may live in a cloud-synced folder (iCloud Drive /
REM  OneDrive). Qt (the GUI toolkit) is unreliable when its binaries live in a
REM  synced folder (files get evicted to online-only placeholders and fail to
REM  load). So the Python environment is created in a LOCAL folder
REM  (%LOCALAPPDATA%), while your code stays here. Only the .py source is read
REM  from the synced folder, which is fine.
REM ============================================================================
setlocal
title Reference-Warp Tagger

REM --- run from this script's folder ---
cd /d "%~dp0"

echo ======================================================
echo   Reference-Warp Tagger
echo ======================================================
echo.

REM --- find Python 3 (prefer the "py" launcher, then "python") ---
set "PYCMD="
py -3 --version >nul 2>nul
if not errorlevel 1 set "PYCMD=py -3"
if not defined PYCMD (
  python --version >nul 2>nul
  if not errorlevel 1 set "PYCMD=python"
)
if not defined PYCMD (
  echo Python 3 was not found.
  echo Install it from https://www.python.org/downloads/
  echo   ^(during setup, tick "Add python.exe to PATH"^).
  echo.
  pause
  exit /b 1
)
for /f "delims=" %%v in ('%PYCMD% --version 2^>^&1') do echo Python: %%v

REM --- LOCAL virtual environment (outside any synced folder), own dir ---
set "VENV=%LOCALAPPDATA%\HydrogelMarkerGUI\reference_warp_tagger"

if not exist "%VENV%\Scripts\python.exe" (
  echo.
  echo First run - creating a local environment and installing libraries.
  echo   location: %VENV%
  echo   ^(a few minutes; only happens once^)
  %PYCMD% -m venv "%VENV%"
  if errorlevel 1 (
    echo.
    echo Creating the environment failed.
    pause
    exit /b 1
  )
  call "%VENV%\Scripts\activate.bat"
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo Installing the libraries failed ^(check your internet connection^).
    pause
    exit /b 1
  )
) else (
  call "%VENV%\Scripts\activate.bat"
)

echo.
echo Launching the GUI...  ^(close the window to quit^)
python run.py
if errorlevel 1 (
  echo.
  echo The GUI exited with an error.
  echo If it crashed on start: copy this whole project folder OUT of the
  echo cloud-synced folder ^(iCloud Drive / OneDrive^) to e.g. your Desktop and
  echo run it from there, then delete this folder so it rebuilds:
  echo   %VENV%
  echo.
  pause
)
endlocal
