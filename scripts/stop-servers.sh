#!/bin/zsh
# Разовая остановка серверов (LaunchAgent остаётся и поднимет их снова).
set -uo pipefail
pkill -f "uvicorn gateway:app" 2>/dev/null || true
sleep 0.5
pgrep -fl "uvicorn gateway" || echo "серверы остановлены"
