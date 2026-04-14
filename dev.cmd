@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [aimoiveDownload] 安装根目录依赖（concurrently）...
call npm install
if errorlevel 1 exit /b 1
echo.
echo [aimoiveDownload] 启动后端 8003 + 前端 Vite 5173 ...
echo 浏览器请打开: http://127.0.0.1:5173/frontend/
echo 按 Ctrl+C 可停止。
echo.
call npm run dev
pause
