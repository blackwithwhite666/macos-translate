"""Компактная Streamlit-панель для окошка перевода (WKWebView в NSPanel).

Параметры URL (их подставляет Swift-обёртка):
    ?text=...   — выделенный текст (авто-перевод при загрузке)
    &target=... — целевой язык (имя из languages.py)
    &t=...      — nonce, чтобы одинаковый текст запускал перевод заново

Стримит токены из POST /translate gateway (SSE). Готовый перевод выводится
в div.mt-translation — на слова в нём наводит курсор пользователь, а
JS-слой Swift-обёртки показывает снизу карточку из системного словаря.
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

logging.basicConfig(level=logging.INFO)
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

# Новая ссылка с текстом → сброс и автозапуск
if q_text and ss["auto_key"] != f"{q_nonce}|{q_text[:200]}":
    ss["text"] = q_text
    ss["result"] = ""
    ss["detected"] = None
    ss["auto_key"] = f"{q_nonce}|{q_text[:200]}"
    ss["run_now"] = True


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


# --- UI ---------------------------------------------------------------------

top1, top2 = st.columns([3, 2], vertical_alignment="center")
with top1:
    if ss["detected"]:
        name = ss["detected"].get("language") or ss["detected"].get("lingua_name") or "?"
        conf = ss["detected"].get("confidence")
        st.caption(
            f"🧭 **{name}**{f' ({conf:.0%})' if conf is not None else ''} → **{ss['target_lang_name']}**"
        )
with top2:
    target = st.selectbox(
        "Перевести на",
        targets,
        index=targets.index(q_target) if q_target in targets else 0,
        key="target_lang_name",
        label_visibility="collapsed",
    )

text = st.text_area(
    "Исходный текст",
    key="text",
    height=110,
    label_visibility="collapsed",
    placeholder="Текст появится здесь, когда вы его выделите и вызовете перевод…",
)

run = st.button("Перевести", type="primary", use_container_width=True)
if ss.pop("run_now", False) or run:
    if not (ss["text"] or "").strip():
        st.warning("Введите текст для перевода", icon="⚠️")
    else:
        payload = {"text": ss["text"], "src": "auto", "tgt": ss["target_lang_name"]}
        box = st.empty()
        acc: list[str] = []
        detected: dict[str, Any] | None = None
        for event, data in sse_events(payload):
            if event == "status":
                box.markdown(f"⏳ _{STATUS_LABELS.get(data.get('phase'), data.get('phase', '…'))}_")
            elif event == "detect":
                detected = data
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

# Готовый перевод: div.mt-translation — на него реагирует словарный слой Swift.
if ss["result"]:
    esc = html.escape(ss["result"])
    st.markdown(
        f"""
        <style>
        .mt-translation {{
            white-space: pre-wrap;
            font-size: 14.5px;
            line-height: 1.55;
            padding: 12px 14px;
            border: 1px solid rgba(128,128,140,.35);
            border-radius: 10px;
            cursor: default;
        }}
        </style>
        <div class="mt-translation">{esc}</div>
        """,
        unsafe_allow_html=True,
    )
else:
    st.caption("_Перевод появится здесь_")

# Место под карточку словаря (она рисуется поверх, снизу окна)
with st.container(height=150, border=False):
    st.caption("📖 Наведите курсор на слово в переводе — покажу статью из системного словаря")
