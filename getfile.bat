@echo off
setlocal enabledelayedexpansion

REM Check for python
where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Please install Python 3.
  exit /b 1
)

REM Check for pip
python -m pip --version >nul 2>nul
if errorlevel 1 (
  echo pip is not installed. Please install pip for Python 3.
  exit /b 1
)

echo Checking dependencies...
python -m pip show requests >nul 2>nul
if errorlevel 1 goto install
python -m pip show rich >nul 2>nul
if errorlevel 1 goto install
goto run

:install
echo Installing dependencies...
python -m pip install --quiet --upgrade pip >nul 2>nul
python -m pip install --quiet -r requirements.txt >nul 2>nul

:run
REM Run the script (output visible)
python getfile.py %*