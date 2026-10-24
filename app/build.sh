#!/bin/zsh
# Сборка MacOSTranslate.app: фронтенд (один index.html) → бандл → swiftc.
set -euo pipefail
cd "$(dirname "$0")"

ROOT="$(cd .. && pwd)"

# 1) Языки для селектов — генерируются из server/languages.py
cd "$ROOT"
uv run --project server python scripts/gen-languages.py

# 2) Фронтенд: TypeScript → один минифицированный index.html
cd "$ROOT/frontend"
if [ ! -d node_modules ]; then npm install --no-fund --no-audit; fi
npm run typecheck
npm run build
test -f dist/index.html

# 3) Свифт + ресурсы
cd "$ROOT/app"
APP="build/MacOSTranslate.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/frontend"
cp ../frontend/dist/index.html "$APP/Contents/Resources/frontend/"

swiftc -O -module-name MacOSTranslate \
  -framework AppKit -framework WebKit -framework CoreServices \
  -o "$APP/Contents/MacOS/MacOSTranslate" \
  Sources/*.swift

cp Resources/Info.plist "$APP/Contents/Info.plist"
codesign --force --sign - "$APP"

echo "Готово: $(cd build && pwd)/MacOSTranslate.app"
