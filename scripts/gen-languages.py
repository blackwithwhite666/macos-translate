"""Генерирует frontend/src/languages.ts из server/languages.py.

Запуск: uv run python scripts/gen-languages.py (или через build.sh).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "server"))

from languages import ALL_LANGUAGES, BIDIRECTIONAL  # noqa: E402

COMMON = [
    "Russian",
    "English",
    "German",
    "French",
    "Spanish",
    "Italian",
    "Ukrainian",
    "Chinese",
    "Japanese",
    "Portuguese",
]

ts = (
    "// Сгенерировано scripts/gen-languages.py — не править руками.\n"
    f"export const SOURCES: string[] = {json.dumps(sorted(BIDIRECTIONAL), ensure_ascii=False)};\n"
    f"export const COMMON_TARGETS: string[] = {json.dumps(COMMON, ensure_ascii=False)};\n"
    "export const ALL_TARGETS: string[] = [\n"
    f"  ...COMMON_TARGETS,\n"
    f"  ...{json.dumps(sorted(set(ALL_LANGUAGES) - set(COMMON)), ensure_ascii=False)},\n"
    "];\n"
)

out = ROOT / "frontend" / "src" / "languages.ts"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(ts, encoding="utf-8")
print(f"OK: {out} ({len(sorted(BIDIRECTIONAL))} источников, {len(ALL_LANGUAGES)} целей)")
