#!/usr/bin/env bash
set -euo pipefail

# 切到项目根目录
cd "$(dirname "$0")"

# 若无虚拟环境则自动创建并安装依赖
if [[ ! -d .venv ]]; then
  echo "[setup] Creating venv and installing requirements ..."
  python3 -m venv .venv
  source .venv/bin/activate
  python -m pip install -U pip
  pip -q install -r requirements.txt
else
  source .venv/bin/activate
fi

export PYTHONUNBUFFERED=1
export LANG=zh_CN.UTF-8
export LC_ALL=zh_CN.UTF-8

echo "[run] Starting main.py ..."
python main.py

