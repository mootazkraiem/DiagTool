@echo off
echo Starting Build... > build_log_batch.txt
dotnet build CANvisionNative.csproj -c Debug -f net48 >> build_log_batch.txt 2>&1
echo Build Finished with exit code %ERRORLEVEL% >> build_log_batch.txt
