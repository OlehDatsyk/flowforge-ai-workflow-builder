@echo off
setlocal
cd /d "%~dp0"
if "%FLOWFORGE_PORT%"=="" set "FLOWFORGE_PORT=8000"

for /f "delims=" %%i in ('python scripts\venv_path.py') do set "VENV=%%i"
if not exist "%VENV%\Scripts\python.exe" (
  echo FlowForge AI is not set up yet. Run setup.bat first.
  exit /b 1
)

pushd backend
"%VENV%\Scripts\python.exe" -m alembic upgrade head
if errorlevel 1 ( popd & exit /b 1 )
popd

echo.
echo FlowForge AI is running at http://localhost:%FLOWFORGE_PORT%
echo Press Ctrl+C to stop it.
echo.
if not "%FLOWFORGE_NO_BROWSER%"=="1" start "" "http://localhost:%FLOWFORGE_PORT%"
"%VENV%\Scripts\python.exe" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port %FLOWFORGE_PORT%
endlocal
