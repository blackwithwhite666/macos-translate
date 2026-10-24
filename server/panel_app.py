"""Компактная Streamlit-панель для окошка перевода (WKWebView в NSPanel).

Страница грузится один раз; новые выделения панель подхватывает сама,
опрашивая GET /pending (st.fragment, раз в секунду) — без перезагрузки.
Исходный текст и перевод показываются как div-блоки .mt-source /
.mt-translation: наведение на слово в любом из них открывает снизу
карточку из системного словаря (JS-слой Swift-обёртки). «✏️» — редактировать.
"""

from __future__ import annotations

import html
import json
import logging
import os
from collections.abc import Iterator
from typing import Any

import httpx
import streamlit as st

from languages import ALL_LANGUAGES

logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("panel")

API = os.environ.get("MT_API", "http://127.0.0.1:8765")
DEFAULT_TARGET = os.environ.get("MT_DEFAULT_TARGET", "Russian")
COMMON_TARGETS = [
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
STATUS_LABELS = {
    "detecting": "Определяю язык…",
    "loading-model": "Подгружаю модель (первый запуск ~10 с)…",
    "generating": "Перевожу…",
}

st.set_page_config(page_title="Перевод", page_icon="🌐", layout="wide")

ZONE_CSS = """
<style>
.mt-source, .mt-translation {
    white-space: pre-wrap;
    font-size: 13.5px;
    line-height: 1.5;
    padding: 8px 10px;
    border: 1px solid rgba(128,128,140,.3);
    border-radius: 8px;
    overflow-wrap: anywhere;
}
.mt-source {
    max-height: 128px;
    overflow-y: auto;
    color: #c9c9d1;
}
.mt-translation {
    min-height: 96px;
    color: #ececf2;
    font-size: 14px;
}
</style>
"""
st.markdown(ZONE_CSS, unsafe_allow_html=True)

params = st.query_params
q_text = params.get("text") or ""
q_nonce = params.get("t") or ""
q_target = params.get("target") or DEFAULT_TARGET
if q_target not in ALL_LANGUAGES:
    q_target = DEFAULT_TARGET

targets = COMMON_TARGETS + sorted(set(ALL_LANGUAGES) - set(COMMON_TARGETS))

ss = st.session_state
ss.setdefault("text", q_text)
ss.setdefault("result", "")
ss.setdefault("detected", None)
ss.setdefault("auto_key", None)
ss.setdefault("pending_seen", None)
ss.setdefault("editing", False)


def _pending_state() -> dict[str, Any]:
    try:
        r = httpx.get(f"{API}/pending", timeout=1.5)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, json.JSONDecodeError):
        return {"text": None, "mtime_ns": 0, "size": 0}


# Первая загрузка с ?text=… (Swift открывает панель впервые)
if q_text and ss["auto_key"] != f"{q_nonce}|{q_text[:200]}":
    ss["text"] = q_text
    ss["result"] = ""
    ss["detected"] = None
    ss["auto_key"] = f"{q_nonce}|{q_text[:200]}"
    ss["run_now"] = True
    ss["editing"] = False
    p = _pending_state()
    ss["pending_seen"] = (p["mtime_ns"], p["size"])
st.query_params.clear()  # чтобы reconnect/reload не переиграл старый текст


# Новый выделение из фрагмента — забираем ДО создания виджетов (иначе
# Streamlit не даёт менять session_state по ключу виджета)
_incoming = ss.pop("incoming", None)
if _incoming is not None and _incoming.strip() and _incoming != ss.get("text"):
    ss["text"] = _incoming
    ss["result"] = ""
    ss["detected"] = None
    ss["run_now"] = True
    ss["editing"] = False


@st.fragment(run_every="1s")
def _poll_pending() -> None:
    """Подхватывает новое выделение без перезагрузки страницы."""
    p = _pending_state()
    key = (p["mtime_ns"], p["size"])
    text = (p.get("text") or "").strip()
    if text and key != ss.get("pending_seen"):
        ss["pending_seen"] = key
        ss["incoming"] = text
        st.rerun()


def sse_events(payload: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """POST /translate, разбор SSE: yield (event, data)."""
    with (
        httpx.Client(timeout=httpx.Timeout(connect=3, read=None, write=5, pool=5)) as client,
        client.stream("POST", f"{API}/translate", json=payload) as r,
    ):
        if r.status_code != 200:
            st.error(f"Сервер перевода недоступен ({r.status_code})", icon="⚠️")
            return
        event = ""
        for line in r.iter_lines():
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                try:
                    data = json.loads(line[len("data:") :].strip())
                except json.JSONDecodeError:
                    continue
                yield event, data
                event = ""


# --- Верхняя строка: детект + целевой язык + правка --------------------------

c_badge, c_target, c_edit = st.columns([7, 6, 1], vertical_alignment="center")
with c_badge:
    if ss["detected"]:
        name = ss["detected"].get("language") or ss["detected"].get("lingua_name") or "?"
        conf = ss["detected"].get("confidence")
        suffix = f" ({conf:.0%})" if conf is not None else ""
        st.markdown(f"🧭 **{name}**{suffix} → **{ss['target_lang_name']}**")
with c_target:
    st.selectbox(
        "Перевести на",
        targets,
        index=targets.index(q_target) if q_target in targets else 0,
        key="target_lang_name",
        label_visibility="collapsed",
    )
with c_edit:
    if ss["editing"]:
        st.button(
            "✅",
            key="done_edit",
            help="Вернуться к просмотру",
            on_click=lambda: ss.update(editing=False),
        )
    else:
        st.button(
            "✏️", key="start_edit", help="Изменить текст", on_click=lambda: ss.update(editing=True)
        )

# --- Исходный текст ----------------------------------------------------------

if ss["editing"]:
    st.text_area(
        "Исходный текст",
        key="text",
        height=88,
        label_visibility="collapsed",
    )
elif (ss["text"] or "").strip():
    st.markdown(
        f'<div class="mt-source">{html.escape(ss["text"])}</div>',
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        '<div class="mt-source" style="opacity:.45">Выделите текст в любом '
        "приложении и вызовите «Перевести»…</div>",
        unsafe_allow_html=True,
    )

run = st.button("Перевести", "primary", use_container_width=True)

# --- Перевод ------------------------------------------------------------------

if ss.pop("run_now", False) or run:
    if not (ss["text"] or "").strip():
        st.warning("Введите текст для перевода", icon="⚠️")
    else:
        payload = {"text": ss["text"], "src": "auto", "tgt": ss["target_lang_name"]}
        box = st.empty()
        acc: list[str] = []
        for event, data in sse_events(payload):
            if event == "status":
                box.markdown(f"⏳ _{STATUS_LABELS.get(data.get('phase'), data.get('phase', '…'))}_")
            elif event == "detect":
                ss["detected"] = data
            elif event == "token":
                acc.append(data.get("text", ""))
                box.text("".join(acc))
            elif event == "done":
                ss["result"] = data.get("translation", "")
                st.rerun()
            elif event == "error":
                box.empty()
                st.error(data.get("message", "Ошибка перевода"), icon="⚠️")

if ss["result"]:
    st.markdown(
        f'<div class="mt-translation">{html.escape(ss["result"])}</div>',
        unsafe_allow_html=True,
    )

_poll_pending()
