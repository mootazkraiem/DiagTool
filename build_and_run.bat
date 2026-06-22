@echo off
setlocal enabledelayedexpansion

echo [1/4] Cleaning build artifacts...
if exist bin rd /s /q bin
if exist obj rd /s /q obj

echo [2/4] Restoring dependencies...
dotnet restore

echo [3/4] Building CANvision Native Garage...
dotnet build -c Debug --no-restore
if %errorlevel% neq 0 (
    echo [ERROR] Build failed. Check the output above.
    pause
    exit /b %errorlevel%
)

echo [4/4] Launching application...
start "" "bin\Debug\net48\CANvisionNative.exe"

echo.
echo Application started from: %CD%
echo Done.
pause
