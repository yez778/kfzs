@echo off
chcp 65001 >nul
title 星途商城管理后台 (Vue)
echo ============================================
echo   星途户外照明 · 商城管理后台 (client)
echo ============================================
echo.
echo  [1/2] 启动后端 server（内含 AI 智能客服）：
echo        cd server ^&^& python -m uvicorn app.main:app --port 8000
echo.
echo  [2/2] 管理台静态服务 http://localhost:3000
echo        （3000 已在后端 CORS 白名单内）
echo.
echo  浏览器将自动打开，按 Ctrl+C 停止。
start "" "http://localhost:3000"
python -m http.server 3000
pause
