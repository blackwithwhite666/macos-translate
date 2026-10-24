#!/bin/zsh
# Тело Quick Action (Automator → «Run Shell Script», «Pass input: to stdin»).
# Выделенный текст приходит на stdin; можно вызывать и вручную:
#   echo "Hello" | ~/projects/macos-translate/scripts/quick-action.sh
# Целевой язык можно передать первым аргументом (имя из server/languages.py):
#   echo "Привет" | quick-action.sh English

TARGET="${1:-Russian}"
DIR="$HOME/.local/state/macos-translate"
mkdir -p "$DIR"
cat > "$DIR/pending.txt"
open -g "macos-translate://translate?target=$TARGET"
