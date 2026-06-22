@echo off
REM Start the CANvision Native application with backend server
REM This script ensures the Python backend is running before starting the UI

echo ========================================
echo CANvision Native - Startup Script
echo ========================================
echo.

setlocal enabledelayedexpansion

REM Check if Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH
    echo Please install Python 3.9+ and ensure it's in your PATH
    pause
    exit /b 1
)

echo [1/3] Starting Python backend server...
echo The backend server will run on http://127.0.0.1:8765
echo.

REM Start the backend server in a new window
start "CANvision Backend Server" cmd /k "cd /d %CD% && python main.py"

REM Wait for backend to start
echo [2/3] Waiting for backend to initialize (10 seconds)...
timeout /t 10 /nobreak

REM Check if backend is responsive
echo [3/3] Verifying backend server is running...
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri 'http://127.0.0.1:8765/health' -UseBasicParsing -TimeoutSec 5 | Out-Null; Write-Host 'Backend server is ready!' } catch { Write-Host 'Warning: Could not reach backend server. Make sure it started correctly.' }"

echo.
echo ========================================
echo Starting CANvision Native application...
echo ========================================
echo.

REM Build and run the C# application
dotnet build -c Debug --no-restore
if %errorlevel% neq 0 (
    echo [ERROR] Build failed
    pause
    exit /b %errorlevel%
)

start "" "bin\Debug\net48\CANvisionNative.exe"

echo.
echo Backend server and application started.
echo Press Ctrl+C in the backend window to stop the server.
echo.
pause
