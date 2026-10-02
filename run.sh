#!/usr/bin/env bash
# B站直播辅助助手 —— macOS / Linux 启动脚本
set -e
cd "$(dirname "$0")"

echo "============================================================"
echo "  B站直播辅助助手 启动器"
echo "============================================================"

PYTHON=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done

if [ -z "$PYTHON" ]; then
  echo "[错误] 没有找到可用的 Python 解释器，请先安装 Python 3.10 或更高版本。"
  exit 1
fi

echo "[1/3] 使用解释器: $PYTHON"

if [ ! -d ".venv" ]; then
  echo "[2/3] 首次运行，正在创建虚拟环境..."
  "$PYTHON" -m venv .venv
else
  echo "[2/3] 虚拟环境已就绪"
fi

echo "[3/3] 检查依赖..."
".venv/bin/python" -m pip install --quiet --disable-pip-version-check -r requirements.txt \
  || echo "[警告] 依赖安装可能失败，尝试直接启动..."

echo
exec ".venv/bin/python" main.py
