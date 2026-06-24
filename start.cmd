@echo off
title StoryDive

echo.
echo   ========================================
echo          StoryDive
echo   ========================================
echo.

cd /d "F:\.workspace\StoryDive"

echo [1/2] Starting backend (port 8800)...
start "StoryDive Backend" ".venv\Scripts\python.exe" "backend\server.py"

echo [2/2] Waiting for server...
:wait
timeout /t 2 /nobreak >nul
curl -s http://localhost:8800/api/books >nul 2>&1
if %errorlevel% neq 0 goto wait

echo.
echo   ========================================
echo        Backend ready! Opening frontend...
echo   ========================================
echo.
echo   Configure LLM API in Settings page.
echo.
echo   Close this window to stop backend.
echo   ========================================
echo.

start "" "frontend\index.html"

echo Backend running. Press any key to stop...
pause >nul
taskkill /fi "WINDOWTITLE eq StoryDive Backend" /f >nul 2>&1