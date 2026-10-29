@echo off
chcp 65001 >nul
title 星途商城后端 (server)
setlocal
cd /d "%~dp0server"

:: Prefer local Anaconda Python; fall back to python on PATH
set "PY=python"
if exist "D:\Anaconda3\python.exe" set "PY=D:\Anaconda3\python.exe"

echo ================================================
echo   Xingtu Customer Service Backend (server)
echo   URL : http://127.0.0.1:8000
echo   Docs: http://127.0.0.1:8000/docs
echo ================================================
echo.

"%PY%" -c "import fastapi, uvicorn, sqlalchemy, chromadb, langgraph" >nul 2>&1
if errorlevel 1 (
  echo [!] Missing dependencies for: %PY%
  echo     Run: "%PY%" -m pip install -r requirements.txt
  echo.
  pause
  exit /b 1
)

echo Using interpreter: %PY%
echo Starting... press Ctrl+C to stop
echo.

"%PY%" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

if errorlevel 1 (
  echo.
  echo [!] Backend exited. See the error above.
  pause
)
