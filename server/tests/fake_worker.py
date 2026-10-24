"""Фейковый воркер для тестов gateway: тот же JSONL-протокол, без модели.

MT_FAKE_MODEL в worker.py разворачивает тот же фейк внутри настоящего воркера,
здесь — минимальная независимая версия.
"""

import json
import sys

print(json.dumps({"event": "ready", "model": "fake"}), flush=True)

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    req = json.loads(line)
    rid = req.get("id")
    cmd = req.get("cmd")
    if cmd == "ping":
        print(json.dumps({"id": rid, "event": "pong"}), flush=True)
    elif cmd == "translate":
        text = req.get("text", "")
        tgt = req.get("tgt", "?")
        out = f"[{tgt}] {text}"
        for i in range(0, len(out), 7):
            print(
                json.dumps(
                    {"id": rid, "event": "token", "text": out[i : i + 7]}, ensure_ascii=False
                ),
                flush=True,
            )
        print(
            json.dumps(
                {
                    "id": rid,
                    "event": "done",
                    "translation": out,
                    "prompt_tokens": 10,
                    "gen_tokens": len(out),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    else:
        print(json.dumps({"id": rid, "event": "error", "message": f"unknown {cmd}"}), flush=True)
