#!/bin/zsh
# Ставит LaunchAgent: сервер перевода (gateway + панель) стартует при входе
# и перезапускается при падении. Сама модель живёт в подпроцессе gateway
# и выгружается после MT_IDLE_TIMEOUT секунд простоя (по умолчанию 600).

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="local.macos-translate.server"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$HOME/Library/LaunchAgents" "$REPO/logs"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/zsh</string>
        <string>-l</string>
        <string>-c</string>
        <string>exec '$REPO/server/run.sh'</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>WorkingDirectory</key>
    <string>$REPO</string>
    <key>ProcessType</key>
    <string>Adaptive</string>
    <key>StandardOutPath</key>
    <string>$REPO/logs/launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>$REPO/logs/launchd.err.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart "gui/$(id -u)/$LABEL"

echo "OK: $LABEL установлен и запущен (репозиторий: $REPO)"
echo "Логи: $REPO/logs/"
