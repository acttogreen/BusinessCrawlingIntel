@echo off
setlocal

cd /d "%~dp0"
set "PROJECT_ROOT=%~dp0"
set "PYTHON=%PROJECT_ROOT%.venv\Scripts\python.exe"
set "FRONTEND=%PROJECT_ROOT%frontend"
set "API_URL=http://127.0.0.1:8000"
set "FRONTEND_URL=http://localhost:5173"

echo Stopping existing BusinessCrawlingIntel services...
for /f "usebackq tokens=*" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$ports=8000,5173; Get-NetTCPConnection -LocalPort $ports -State Listen,Established,CloseWait,FinWait1,FinWait2 -ErrorAction SilentlyContinue ^| Select-Object -ExpandProperty OwningProcess -Unique"`) do (
    if not "%%P"=="" (
        echo Stopping process tree %%P...
        taskkill /PID %%P /T /F >nul 2>&1
    )
)

rem Also close stale launcher windows from this project that no longer own a port.
for /f "usebackq tokens=*" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$root=[regex]::Escape('%PROJECT_ROOT%'); Get-CimInstance Win32_Process -Filter 'Name = ''python.exe''' -ErrorAction SilentlyContinue ^| Where-Object { $_.CommandLine -match $root -and $_.CommandLine -match 'backend[\\/]run_server\.py' } ^| Select-Object -ExpandProperty ProcessId"`) do (
    if not "%%P"=="" (
        echo Stopping stale backend process %%P...
        taskkill /PID %%P /T /F >nul 2>&1
    )
)

timeout /t 1 /nobreak >nul

if not exist "%PYTHON%" (
    echo [ERROR] Python virtual environment not found:
    echo         %PYTHON%
    pause
    exit /b 1
)

if not exist "%FRONTEND%\node_modules" (
    echo [ERROR] Frontend dependencies not found:
    echo         %FRONTEND%\node_modules
    echo.
    echo Run: cd frontend ^&^& npm install
    pause
    exit /b 1
)

echo Starting FastAPI backend at %API_URL%...
start "BusinessCrawlingIntel Backend" /D "%PROJECT_ROOT%" cmd /k call "%PYTHON%" backend\run_server.py

echo Starting Vite frontend...
start "BusinessCrawlingIntel Frontend" /D "%FRONTEND%" cmd /k "set VITE_API_BASE=%API_URL%&& npm run dev -- --host localhost"

timeout /t 5 /nobreak >nul
start "" "%FRONTEND_URL%"

endlocal
exit /b 0
