"""Подпроцесс с моделью TranslateGemma (MLX).

Говорит JSONL по stdin/stdout:
    -> {"id":1,"cmd":"translate","text":"...","src":"English","tgt":"Russian"}
    <- {"id":1,"event":"token","text":"При"} ...
    <- {"id":1,"event":"done","translation":"...","prompt_tokens":n,"gen_tokens":m}

Живёт, пока открыт stdin: EOF = завершиться (так gateway выгружает модель
и освобождает ~4 ГБ памяти). MT_FAKE_MODEL=1 — фейковый стрим для тестов.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from languages import ALL_LANGUAGES

MODEL_ID = "mlx-community/translategemma-4b-it-8bit"
# Как в translategemma-studio: бюджет промпта 1024 токена, всё остальное — ответ.
CONTEXT_WINDOW = 2048
MAX_PROMPT_TOKENS = 1024


def build_prompt(
    text: str,
    src_lang: str,
    src_code: str,
    tgt_lang: str,
    tgt_code: str,
) -> str:
    # Шаблон 1-в-1 из TranslateGemma Studio (проверен там на качество).
    instruction = (
        f"You are a professional {src_lang} ({src_code}) to {tgt_lang} "
        f"({tgt_code}) translator. Your goal is to accurately convey the meaning and "
        f"nuances of the original {src_lang} text while adhering to {tgt_lang} grammar, "
        f"vocabulary, and cultural sensitivities.\nProduce only the {tgt_lang} "
        f"translation, without any additional explanations or commentary. Please translate "
        f"the following {src_lang} text into {tgt_lang}:\n\n\n{text}"
    )
    return f"<start_of_turn>user\n{instruction}<end_of_turn>\n<start_of_turn>model\n"


def _emit(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _fake_stream(text: str, tgt_code: str):
    out = f"[{tgt_code}] {text}"
    for i in range(0, len(out), 7):
        yield out[i : i + 7]


def _translate(rid: int, req: dict[str, Any], model: Any, tokenizer: Any, fake: bool) -> None:
    text = (req.get("text") or "").strip()
    src = req.get("src", "English")
    tgt = req.get("tgt", "English")
    if not text:
        _emit({"id": rid, "event": "error", "message": "пустой текст"})
        return
    if src == tgt:
        _emit({"id": rid, "event": "error", "message": "исходный язык равен целевому"})
        return
    src_code = ALL_LANGUAGES.get(src)
    tgt_code = ALL_LANGUAGES.get(tgt)
    if not src_code or not tgt_code:
        _emit({"id": rid, "event": "error", "message": f"неизвестный язык: {src!r}/{tgt!r}"})
        return

    prompt = build_prompt(text, src, src_code, tgt, tgt_code)
    pieces: list[str] = []
    prompt_tokens = 0
    gen_tokens = 0

    if fake:
        prompt_tokens = max(1, len(prompt) // 4)
        for piece in _fake_stream(text, tgt_code):
            pieces.append(piece)
            _emit({"id": rid, "event": "token", "text": piece})
        gen_tokens = max(1, len("".join(pieces)) // 4)
    else:
        from mlx_lm import stream_generate

        prompt_tokens = len(tokenizer.encode(prompt))
        if prompt_tokens > MAX_PROMPT_TOKENS:
            _emit(
                {
                    "id": rid,
                    "event": "error",
                    "message": (
                        f"ввод слишком длинный: {prompt_tokens} токенов промпта "
                        f"(лимит {MAX_PROMPT_TOKENS})"
                    ),
                }
            )
            return
        for resp in stream_generate(
            model, tokenizer, prompt=prompt, max_tokens=CONTEXT_WINDOW - prompt_tokens
        ):
            piece = resp.text
            pieces.append(piece)
            if resp.generation_tokens:
                gen_tokens = resp.generation_tokens
            _emit({"id": rid, "event": "token", "text": piece})

    translation = "".join(pieces).split("<end_of_turn>", 1)[0].strip()
    _emit(
        {
            "id": rid,
            "event": "done",
            "translation": translation,
            "prompt_tokens": prompt_tokens,
            "gen_tokens": gen_tokens,
        }
    )


def main() -> int:
    _emit({"event": "booting", "model": MODEL_ID})
    fake = bool(os.environ.get("MT_FAKE_MODEL"))
    model = tokenizer = None
    if not fake:
        try:
            from mlx_lm import load

            loaded = load(MODEL_ID)
            if len(loaded) != 2:
                raise RuntimeError(f"mlx_lm.load() вернул {len(loaded)} значений, ожидал 2")
            model, tokenizer = loaded
            tokenizer.add_eos_token("<end_of_turn>")
        except Exception as e:  # noqa: BLE001
            _emit({"event": "fatal", "message": str(e)})
            return 1
    _emit({"event": "ready", "model": "fake" if fake else MODEL_ID, "fake": fake})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            _emit({"id": None, "event": "error", "message": f"битый json: {e}"})
            continue
        rid = req.get("id")
        cmd = req.get("cmd")
        if cmd == "ping":
            _emit({"id": rid, "event": "pong"})
        elif cmd == "shutdown":
            break
        elif cmd == "translate":
            _translate(rid, req, model, tokenizer, fake)
        else:
            _emit({"id": rid, "event": "error", "message": f"неизвестная команда: {cmd!r}"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
