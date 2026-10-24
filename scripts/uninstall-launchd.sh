#!/bin/zsh
# Удаляет LaunchAgent и останавливает серверы.
set -uo pipefail
LABEL="local.macos-translate.server"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
pkill -f "uvicorn gateway:app" 2>/dev/null || true
echo "OK: $LABEL удалён"
