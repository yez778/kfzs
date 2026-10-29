@echo off
chcp 65001 >nul
title 星途 AI 智能客服 (agent)
cd /d "%~dp0agent"
echo ================================================
echo   Xingtu AI Customer Service (agent)
echo   URL : http://127.0.0.1:8100
echo   LLM_PROVIDER=mock（本地演示，无需 API Key）
echo   DeepSeek 模式：设置 LLM_API_KEY 环境变量
echo ================================================
echo.
python -m uvicorn app:app --reload --host 127.0.0.1 --port 8100
pause
