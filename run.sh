#!/usr/bin/env bash
# 一键启动 AI 批改作业系统
set -euo pipefail

cd "$(dirname "$0")"

# 1. 检查 .env
if [ ! -f .env ]; then
  echo "[i] 未发现 .env，从 .env.example 复制。请编辑后填入 ANTHROPIC_API_KEY。"
  cp .env.example .env
fi

# 2. 准备 venv
if [ ! -d .venv ]; then
  echo "[i] 创建 Python 虚拟环境 .venv"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 3. 装依赖（只在缺 anthropic 时装）
if ! python -c "import anthropic" 2>/dev/null; then
  echo "[i] 安装 Python 依赖…"
  pip install --upgrade pip >/dev/null
  pip install -r backend/requirements.txt
fi

# 4. 启动 uvicorn
export PYTHONPATH="$(pwd)/backend"
PORT="${PORT:-8000}"
echo "[✓] 打开浏览器: http://localhost:$PORT"
echo "[i] 按 Ctrl+C 停止"

# 后台打开浏览器（Mac）
if command -v open >/dev/null; then
  (sleep 1 && open "http://localhost:$PORT") &
fi

exec python -m uvicorn main:app --host 0.0.0.0 --port "$PORT" --reload
