#!/bin/zsh
# Сборка MacOSTranslate.app без Xcode-проекта.
set -euo pipefail
cd "$(dirname "$0")"

APP="build/MacOSTranslate.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

swiftc -O -module-name MacOSTranslate \
  -framework AppKit -framework WebKit -framework CoreServices \
  -o "$APP/Contents/MacOSTranslate" \
  Sources/*.swift

cp Resources/Info.plist "$APP/Contents/Info.plist"
codesign --force --sign - "$APP"

echo "Готово: $(cd build && pwd)/MacOSTranslate.app"
