@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
chcp 65001 >nul

echo ============================================================
echo   B站直播辅助助手 启动器
echo ============================================================

set "PYTHON="
if exist ".venv\Scripts\python.exe" set "PYTHON=.venv\Scripts\python.exe"

if not defined PYTHON (
  for %%C in (python py python3) do (
    if not defined PYTHON (
      %%C -c "import sys" >nul 2>&1 && set "PYTHON=%%C"
    )
  )
)

if not defined PYTHON (
  for %%R in ("%APPDATA%\uv\python" "%LOCALAPPDATA%\uv\python" "%LOCALAPPDATA%\Programs\Python" "%ProgramFiles%\Python*") do (
    if not defined PYTHON if exist %%R (
      for /d %%D in (%%R\python* %%R\cpython*) do (
        if not defined PYTHON if exist "%%D\python.exe" set "PYTHON=%%D\python.exe"
      )
    )
  )
)

if not defined PYTHON (
  echo [错误] 没有找到可用的 Python 解释器，请先安装 Python 3.10 或更高版本。
  pause
  exit /b 1
)

echo [1/3] 使用解释器: %PYTHON%

if not exist ".venv\Scripts\python.exe" (
  echo [2/3] 首次运行，正在创建虚拟环境...
  %PYTHON% -m venv .venv
  if errorlevel 1 (
    echo [错误] 创建虚拟环境失败。
    pause
    exit /b 1
  )
) else (
  echo [2/3] 虚拟环境已就绪
)

echo [3/3] 检查依赖...
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo [警告] 依赖安装可能失败，尝试直接启动...
)

echo.
".venv\Scripts\python.exe" main.py

echo.
echo 程序已退出。
pause
