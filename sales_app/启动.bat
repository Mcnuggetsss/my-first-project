@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo 正在关闭旧进程...
taskkill /F /IM python.exe /FI "WINDOWTITLE eq sales*" >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr :5000') do (
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo 正在检查 Flask...
python -c "import flask" 2>nul || (
    echo 正在安装 Flask，请稍候...
    pip install flask -q
)

echo.
echo ========================================
echo   食品批发销售管理系统
echo   请用浏览器打开: http://127.0.0.1:5000
echo ========================================
echo.
timeout /t 1 /nobreak >nul
start "" "http://127.0.0.1:5000"
python app.py
pause
