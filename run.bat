@echo off
setlocal EnableDelayedExpansion

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

if "%SBI_PREFERENCES_KEY%"=="" (
    if exist "%PROJECT_ROOT%preferences\.key" (
        set /p SBI_PREFERENCES_KEY=<"%PROJECT_ROOT%preferences\.key"
    ) else (
        echo Generating encrypted preferences key...
        if not exist "%PROJECT_ROOT%preferences" mkdir "%PROJECT_ROOT%preferences"
        for /f "usebackq delims=" %%K in (`%PYTHON% -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) do set "SBI_PREFERENCES_KEY=%%K"
        if "!SBI_PREFERENCES_KEY!"=="" (
            echo [ERROR] Could not generate SBI_PREFERENCES_KEY.
            pause
            exit /b 1
        )
        >"%PROJECT_ROOT%preferences\.key" echo !SBI_PREFERENCES_KEY!
        attrib +R "%PROJECT_ROOT%preferences\.key" >nul 2>&1
    )
)

echo Starting FastAPI backend at %API_URL%...
echo Encrypted preferences will be stored in %PROJECT_ROOT%preferences\ai_settings.enc
start "BusinessCrawlingIntel Backend" /D "%PROJECT_ROOT%" cmd /k call "%PYTHON%" backend\run_server.py

echo Starting Vite frontend...
start "BusinessCrawlingIntel Frontend" /D "%FRONTEND%" cmd /k "set VITE_API_BASE=%API_URL%&& npm run dev -- --host localhost"

timeout /t 5 /nobreak >nul
start "" "%FRONTEND_URL%"

endlocal
exit /b 0
