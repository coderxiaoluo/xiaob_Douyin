@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PORT=19527"
if defined DY_WEB_PORT set "PORT=%DY_WEB_PORT%"

echo.
echo  ========================================
echo   XiaoBo Web Workbench
echo   http://127.0.0.1:%PORT%/
echo  ========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] python not found in PATH
  echo.
  pause
  exit /b 1
)

python -c "import sys; print('[OK] Python', sys.version.split()[0])" 2>nul
if errorlevel 1 (
  echo [ERROR] python cannot run
  echo.
  pause
  exit /b 1
)

if not exist ".env" (
  if exist ".env.example" (
    copy /y ".env.example" ".env" >nul
    echo [INFO] created .env from .env.example
  ) else (
    echo [WARN] .env missing, configure Cookie in web UI later
  )
  echo.
)

REM free port if occupied
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object { Write-Host ('[INFO] kill PID ' + $_); Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }"

echo [START] python -m webapp.server
echo [INFO] Ctrl+C to stop
echo.

start "" "http://127.0.0.1:%PORT%/"
python -m webapp.server
set "ERR=%ERRORLEVEL%"

echo.
if not "%ERR%"=="0" (
  echo [ERROR] server exited with code %ERR%
  echo Common causes:
  echo   1. port %PORT% still in use
  echo   2. missing packages: pip install -r requirements.txt
  echo   3. bad .env / cookie
) else (
  echo [INFO] server stopped
)
echo.
pause
exit /b %ERR%