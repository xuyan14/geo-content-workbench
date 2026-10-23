#!/usr/bin/env bash
# GeoContent Workbench 启动脚本
# 用法: bash scripts/start.sh [端口]   默认 8787
set -e
cd "$(dirname "$0")/.."

PORT="${1:-8787}"

# 优雅结束旧进程
if OLD_PID=$(lsof -ti:"$PORT" -sTCP:LISTEN 2>/dev/null); then
  echo "端口 $PORT 被占用 (PID $OLD_PID)，正在停止…"
  kill $OLD_PID 2>/dev/null || true
  sleep 1
fi

if [ ! -d .venv ]; then
  echo "未找到虚拟环境，创建并安装依赖…"
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

mkdir -p /tmp logs
nohup .venv/bin/python -m uvicorn app.main:app --port "$PORT" --host 0.0.0.0 > "/tmp/geo-workbench.log" 2>&1 &
echo $! > /tmp/geo-workbench.pid

# 等待就绪
for i in $(seq 1 20); do
  if curl -s -o /dev/null -m 2 "http://localhost:$PORT/api/platform"; then
    echo "已启动: http://localhost:$PORT  (PID $(cat /tmp/geo-workbench.pid), 日志 /tmp/geo-workbench.log)"
    exit 0
  fi
  sleep 1
done
echo "启动超时，请查看日志: tail -50 /tmp/geo-workbench.log"
exit 1
