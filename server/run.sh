#!/bin/zsh
# Долгоживущий запуск api (uvicorn, :8765) + панели (streamlit, :8502).
# Предназначен для launchd (KeepAlive) — см. scripts/install-launchd.sh.

set -uo pipefail

SERVER_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SERVER_DIR")"
cd "$ROOT"
mkdir -p logs

# Уже живо? Ничего не делаем, просто спим, чтобы launchd не крутил нас заново.
if curl -sf -m 2 http://127.0.0.1:8765/health >/dev/null 2>&1; then
  echo "$(date -Iseconds) gateway уже здоров — спим" >> logs/server.log
  exec sleep infinity
fi

# Прибить осиротевшие процессы на наших портах.
for port in 8765; do
  pid=$(lsof -ti tcp:$port 2>/dev/null) || true
  if [ -n "${pid:-}" ]; then
    echo "$(date -Iseconds) убиваю сироту на :$port (pid $pid)" >> logs/server.log
    kill $pid 2>/dev/null || true
  fi
done
sleep 0.5

(cd "$SERVER_DIR" && exec uv run uvicorn gateway:app --host 127.0.0.1 --port 8765 --log-level warning) >> logs/server.log 2>&1 &
API_PID=$!

echo "$(date -Iseconds) запущено: api=$API_PID" >> logs/server.log

term() {
  kill $API_PID 2>/dev/null || true
  wait 2>/dev/null || true
  exit 0
}
trap term TERM INT
wait
