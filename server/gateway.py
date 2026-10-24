"""macos-translate gateway.

Постоянно живущий HTTP-сервер (управляется launchd, см. scripts/install-launchd.sh):
    GET  /health    — статус сервера
    POST /detect    — определение языка (lingua-language-detector)
    POST /translate — SSE-стриминг перевода (TranslateGemma через MLX)

Модель живёт в подпроцессе worker.py: порождается по первому запросу,
выгружается после MT_IDLE_TIMEOUT секунд простоя (по умолчанию 600).
Логи переводов: logs/translations.jsonl, жизненный цикл: logs/server.log.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import sys
import time
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from lingua import Language, LanguageDetectorBuilder
from pydantic import BaseModel, Field

from languages import ALL_LANGUAGES, BIDIRECTIONAL

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
TRANSLATIONS_LOG = LOG_DIR / "translations.jsonl"
WORKER_PATH = Path(__file__).resolve().parent / "worker.py"
MODEL_ID = "mlx-community/translategemma-4b-it-8bit"

IDLE_TIMEOUT = float(os.environ.get("MT_IDLE_TIMEOUT", "600"))
REAP_INTERVAL = float(os.environ.get("MT_REAP_INTERVAL", "15"))
READY_TIMEOUT = float(os.environ.get("MT_READY_TIMEOUT", "360"))
EVENT_TIMEOUT = float(os.environ.get("MT_EVENT_TIMEOUT", "600"))

LOG_DIR.mkdir(exist_ok=True)
logger = logging.getLogger("macos-translate")
logger.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
# Только файл: stdout uvicorn'а и так уходит в этот же лог через run.sh —
# второй StreamHandler дал бы дубли каждой строки.
_h = RotatingFileHandler(LOG_DIR / "server.log", maxBytes=1_000_000, backupCount=3)
_h.setFormatter(_fmt)
logger.addHandler(_h)


# --- Определение языка (lingua) -------------------------------------------


def _languages_for_lingua() -> dict[str, Language]:
    """Имя языка из нашего списка -> enum lingua (совпадение по ISO-коду)."""
    by_iso: dict[str, Language] = {}
    for attr in dir(Language):
        if not attr.isupper():
            continue
        lg = getattr(Language, attr)
        if lg.iso_code_639_1:
            by_iso.setdefault(lg.iso_code_639_1.name.lower(), lg)
        if lg.iso_code_639_3:
            by_iso.setdefault(lg.iso_code_639_3.name.lower(), lg)
    out: dict[str, Language] = {}
    for name, code in BIDIRECTIONAL.items():
        base = code.split("-")[0].lower()
        lg = by_iso.get(code.lower()) or by_iso.get(base)
        if lg is not None:
            out[name] = lg
    return out


_detector: Any = None
_name_by_lingua: dict[Language, str] = {}


def _get_detector() -> Any:
    global _detector, _name_by_lingua
    if _detector is None:
        mapping = _languages_for_lingua()
        _name_by_lingua = {lg: name for name, lg in mapping.items()}
        langs = list(dict.fromkeys(mapping.values()))
        builder = (
            LanguageDetectorBuilder.from_languages(*langs)
            if langs
            else LanguageDetectorBuilder.from_all_languages()
        )
        _detector = builder.build()
    return _detector


def detect_language(text: str) -> dict[str, Any]:
    """Топ-язык lingua. Короткие/неоднозначные тексты дают language=None
    (перевод тогда стартует с английского как источника)."""
    values = _get_detector().compute_language_confidence_values(text)
    if not values:
        return {"language": None, "lingua_name": None, "confidence": 0.0, "margin": 0.0}
    top = values[0]
    second = values[1].value if len(values) > 1 else 1.0
    margin = top.value - second
    reliable = top.value >= 0.5 and margin >= 0.15
    lg = top.language
    return {
        "language": _name_by_lingua.get(lg) if reliable else None,
        "lingua_name": lg.name.title() if reliable else None,
        "confidence": round(top.value, 3),
        "margin": round(margin, 3),
    }


# --- Менеджер подпроцесса с моделью ----------------------------------------


class WorkerManager:
    """Один подпроцесс worker.py: spawn по требованию, выгрузка по простою."""

    def __init__(self) -> None:
        self.proc: asyncio.subprocess.Process | None = None
        self.lock = asyncio.Lock()  # один перевод за раз (MLX всё равно последователен)
        self.last_active = 0.0
        self._queues: dict[int, asyncio.Queue] = {}
        self._control: asyncio.Queue = asyncio.Queue()
        self._next_id = 1

    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    def _cmd(self) -> list[str]:
        raw = os.environ.get("MT_WORKER")
        if raw:
            try:  # допускаем и JSON-массив, и shlex-строку
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(x) for x in parsed]
            except json.JSONDecodeError:
                pass
            return shlex.split(raw)
        return [sys.executable, str(WORKER_PATH)]

    async def ensure(self) -> None:
        if self.running():
            self.last_active = time.monotonic()
            return
        self.last_active = time.monotonic()  # считаем простой от старта загрузки
        logger.info("запускаю подпроцесс с моделью: %s", " ".join(self._cmd()))
        self.proc = await asyncio.create_subprocess_exec(
            *self._cmd(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        asyncio.create_task(self._read_stdout())
        deadline = time.monotonic() + READY_TIMEOUT
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("воркер не поднялся за отведённое время")
            ev = await asyncio.wait_for(self._control.get(), timeout=remaining)
            if ev.get("event") == "ready":
                logger.info("модель готова: %s", ev.get("model"))
                break
            if ev.get("event") == "fatal":
                raise RuntimeError(f"воркер упал: {ev.get('message')}")
        self.last_active = time.monotonic()

    def next_id(self) -> int:
        rid = self._next_id
        self._next_id += 1
        return rid

    async def submit(self, payload: dict[str, Any]) -> asyncio.Queue:
        if not (self.proc and self.proc.stdin):
            raise RuntimeError("воркер не запущен")
        q: asyncio.Queue = asyncio.Queue()
        self._queues[payload["id"]] = q
        self.proc.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
        await self.proc.stdin.drain()
        self.last_active = time.monotonic()
        return q

    async def _read_stdout(self) -> None:
        proc = self.proc
        assert proc and proc.stdout
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            s = line.decode(errors="replace").strip()
            if not s:
                continue
            try:
                ev = json.loads(s)
            except json.JSONDecodeError:
                logger.info("worker: %s", s[:200])
                continue
            q = self._queues.get(ev.get("id"))
            if q is not None:
                q.put_nowait(ev)
            else:
                self._control.put_nowait(ev)
        rc = await proc.wait()
        logger.info("подпроцесс с моделью завершился (rc=%s)", rc)
        for q in self._queues.values():
            q.put_nowait({"event": "error", "message": "воркер завершился"})
        self._queues.clear()
        if self.proc is proc:
            self.proc = None

    async def unload(self, reason: str) -> None:
        proc, self.proc = self.proc, None
        if proc is None or proc.returncode is not None:
            return
        logger.info("выгружаю модель: %s", reason)
        try:
            if proc.stdin is not None:
                proc.stdin.close()  # воркер завершается по EOF на stdin
        except (OSError, AttributeError):
            pass
        try:
            await asyncio.wait_for(proc.wait(), 10)
        except TimeoutError:
            proc.kill()

    async def reaper(self) -> None:
        while True:
            await asyncio.sleep(REAP_INTERVAL)
            if (
                self.running()
                and self.last_active
                and time.monotonic() - self.last_active > IDLE_TIMEOUT
            ):
                await self.unload(f"простой {IDLE_TIMEOUT:.0f} с")


mgr = WorkerManager()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    task = asyncio.create_task(mgr.reaper())
    logger.info("gateway поднят (idle_timeout=%.0f с)", IDLE_TIMEOUT)
    try:
        yield
    finally:
        task.cancel()
        await mgr.unload("выключение gateway")


app = FastAPI(title="macos-translate", lifespan=lifespan)


# --- Ручки ------------------------------------------------------------------


class DetectIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class TranslateIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    src: str = "auto"  # "auto" или имя языка из BIDIRECTIONAL
    tgt: str


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "macos-translate",
        "worker_running": mgr.running(),
        "model": MODEL_ID,
        "idle_timeout_s": IDLE_TIMEOUT,
        "languages": len(ALL_LANGUAGES),
    }


@app.post("/detect")
def detect(req: DetectIn) -> dict[str, Any]:
    return detect_language(req.text)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/translate")
async def translate(req: TranslateIn) -> StreamingResponse:
    if req.tgt not in ALL_LANGUAGES:
        raise HTTPException(422, f"неизвестный целевой язык: {req.tgt!r}")
    if req.src != "auto" and req.src not in BIDIRECTIONAL:
        raise HTTPException(422, f"неизвестный исходный язык: {req.src!r}")
    if req.src == req.tgt:
        raise HTTPException(400, "исходный и целевой язык совпадают")

    async def gen() -> AsyncIterator[str]:
        t0 = time.perf_counter()
        detected: dict[str, Any] | None = None
        try:
            src = req.src
            if src == "auto":
                yield _sse("status", {"phase": "detecting"})
                detected = await asyncio.to_thread(detect_language, req.text)
                src = detected["language"] or "English"
                yield _sse("detect", {**detected, "used_as_source": src})
            async with mgr.lock:
                try:
                    await mgr.ensure()
                except Exception as e:
                    logger.exception("не удалось поднять воркер")
                    yield _sse("error", {"message": f"модель не запустилась: {e}"})
                    return
                yield _sse("status", {"phase": "generating"})
                rid = mgr.next_id()
                q = await mgr.submit(
                    {"id": rid, "cmd": "translate", "text": req.text, "src": src, "tgt": req.tgt}
                )
                tokens: list[str] = []
                done: dict[str, Any] = {}
                while True:
                    ev = await asyncio.wait_for(q.get(), timeout=EVENT_TIMEOUT)
                    kind = ev.get("event")
                    if kind == "token":
                        piece = ev.get("text", "")
                        tokens.append(piece)
                        yield _sse("token", {"text": piece})
                    elif kind == "done":
                        done = ev
                        break
                    elif kind == "error":
                        yield _sse("error", {"message": ev.get("message", "ошибка воркера")})
                        return
                translation = done.get("translation", "")
                duration_ms = int((time.perf_counter() - t0) * 1000)
                yield _sse(
                    "done",
                    {
                        "translation": translation,
                        "src": src,
                        "tgt": req.tgt,
                        "prompt_tokens": done.get("prompt_tokens"),
                        "gen_tokens": done.get("gen_tokens"),
                        "duration_ms": duration_ms,
                    },
                )
                _log_translation(req, detected, src, translation, done, duration_ms)
        except TimeoutError:
            yield _sse("error", {"message": "таймаут ожидания модели"})
        except Exception as e:
            logger.exception("translate failed")
            yield _sse("error", {"message": str(e)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _log_translation(
    req: TranslateIn,
    detected: dict[str, Any] | None,
    src: str,
    translation: str,
    done: dict[str, Any],
    duration_ms: int,
) -> None:
    rec = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "src": src,
        "src_detected": (detected or {}).get("language"),
        "src_confidence": (detected or {}).get("confidence"),
        "tgt": req.tgt,
        "input": req.text,
        "output": translation,
        "prompt_tokens": done.get("prompt_tokens"),
        "output_tokens": done.get("gen_tokens"),
        "duration_ms": duration_ms,
        "model": MODEL_ID,
    }
    try:
        with TRANSLATIONS_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        logger.exception("не смог записать лог переводов")
    logger.info(
        "перевёл %d→%d симв. %s→%s за %d мс",
        len(req.text),
        len(translation),
        src,
        req.tgt,
        duration_ms,
    )
