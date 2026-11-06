@echo off
setlocal
cd /d "%~dp0"
echo.
echo === FlowForge AI setup ===
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.11 or newer from https://www.python.org/downloads/ and run this again.
  exit /b 1
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
  echo FlowForge AI needs Python 3.11 or newer.
  exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
  echo Node.js was not found. Install Node.js 20 or newer from https://nodejs.org/ and run this again.
  exit /b 1
)

for /f "delims=" %%i in ('python scripts\venv_path.py') do set "VENV=%%i"
echo [1/5] Python environment: %VENV%
if not exist "%VENV%\Scripts\python.exe" (
  python -m venv "%VENV%"
  if errorlevel 1 exit /b 1
)

echo [2/5] Installing backend dependencies
"%VENV%\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r backend\requirements.txt
if errorlevel 1 exit /b 1

echo [3/5] Creating configuration
"%VENV%\Scripts\python.exe" scripts\ensure_env.py
if errorlevel 1 exit /b 1

echo [4/5] Building the frontend
pushd frontend
call npm install --no-audit --no-fund --loglevel=error
if errorlevel 1 ( popd & exit /b 1 )
call npm run build
if errorlevel 1 ( popd & exit /b 1 )
popd

echo [5/5] Preparing the database
pushd backend
"%VENV%\Scripts\python.exe" -m alembic upgrade head
if errorlevel 1 ( popd & exit /b 1 )
popd

echo.
echo Setup complete. Run start.bat to launch FlowForge AI.
endlocal
