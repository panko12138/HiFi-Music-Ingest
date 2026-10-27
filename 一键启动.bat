@echo off
cd /d "%~dp0"
title 无损音乐检索与自动入库工具

echo ==========================================
echo   无损音乐检索与自动入库工具 - 一键启动
echo ==========================================
echo.

rem ---- 已在运行则直接开页面 ----
netstat -ano | findstr ":8756" | findstr "LISTENING" >nul 2>nul
if not errorlevel 1 (
  echo [提示] 服务已在运行，正在打开页面...
  start "" http://127.0.0.1:8756
  exit /b 0
)

rem ---- 检查 python ----
where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未找到 python，请先安装 Python 3.10 并确保已加入 PATH。
  echo.
  pause
  exit /b 1
)

rem ---- 检查依赖，缺失则从清华镜像安装 ----
python -c "import flask, requests, mutagen, musicdl" >nul 2>nul
if errorlevel 1 (
  echo [提示] 依赖缺失，正在从清华镜像安装，请稍候...
  python -m pip install -r _tool\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
  if errorlevel 1 (
    echo.
    echo [错误] 依赖安装失败，请手动执行：
    echo   python -m pip install -r _tool\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    echo.
    pause
    exit /b 1
  )
)

echo [信息] 正在启动服务，3 秒后自动打开浏览器...
echo [信息] 保持本窗口开启；按 Ctrl+C 可停止服务。
echo.
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3; Start-Process 'http://127.0.0.1:8756'"

python _tool\server.py

echo.
echo [信息] 服务已停止。
pause
