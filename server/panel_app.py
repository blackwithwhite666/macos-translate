"""Компактная Streamlit-панель для окошка перевода (WKWebView в NSPanel).

Страница грузится один раз; новые выделения панель подхватывает сама,
опрашивая GET /pending (st.fragment, раз в секунду) — без перезагрузки.

Раскладка (сверху вниз): исходный текст → селекты «источник → приёмник» →
перевод → карточка словаря (оверлей, по наведению на слово в .mt-source
или .mt-translation). Исходный язык «Авто» подхватывает результат детекта.
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

from languages import ALL_LANGUAGES, BIDIRECTIONAL

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
SOURCE_OPTIONS = ["Авто"] + sorted(BIDIRECTIONAL)
TARGETS = COMMON_TARGETS + sorted(set(ALL_LANGUAGES) - set(COMMON_TARGETS))
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
    max-height: 122px;
    overflow-y: auto;
    color: #c9c9d1;
}
.mt-translation {
    color: #ececf2;
    font-size: 14px;
}
.mt-arrow {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 1.9rem; /* как контрол селекта */
    color: #9aa0ad;
    font-size: 15px;
    line-height: 1;
    margin: 0;
}
.stMarkdown:has(.mt-arrow) p {
    margin: 0 !important;
}
[data-testid="stHorizontalBlock"] {
    flex-wrap: nowrap !important;
}
div[data-baseweb="select"] {
    width: 100% !important;
}
div[data-baseweb="select"] > div {
    width: 100% !important;
    font-size: 0.8rem;
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

ss = st.session_state
ss.setdefault("text", q_text)
ss.setdefault("result", "")
ss.setdefault("detected", None)
ss.setdefault("pending_seen", None)
ss.setdefault("source_user_set", False)


def _pending_state() -> dict[str, Any]:
    try:
        r = httpx.get(f"{API}/pending", timeout=1.5)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, json.JSONDecodeError):
        return {"text": None, "mtime_ns": 0, "size": 0}


def _new_text_arrived(text: str) -> bool:
    """Меняет состояние под новый текст. Только НЕ-виджетные ключи:
    вызывается и сверху (до виджетов), и из фрагмента (после)."""
    if not text.strip() or text == ss.get("text"):
        return False
    ss["text"] = text
    ss["result"] = ""
    ss["detected"] = None
    ss["run_now"] = True
    ss["incoming_source_reset"] = True
    return True


# Всё, что трогает ключи виджетов, — только здесь, до создания виджетов.
if _new_text_arrived(q_text):
    p = _pending_state()
    ss["pending_seen"] = (p["mtime_ns"], p["size"])
st.query_params.clear()  # чтобы reconnect/reload не переиграл старый текст

if ss.pop("incoming_source_reset", False):
    ss["source_lang_name"] = "Авто"
    ss["source_user_set"] = False

# Определённый языком источник подставляем в селект, пока юзер не выбрал сам
detected_src = ss.pop("src_detected_name", None)
if detected_src and not ss.get("source_user_set"):
    ss["source_lang_name"] = detected_src


@st.fragment(run_every="1s")
def _poll_pending() -> None:
    """Подхватывает новое выделение без перезагрузки страницы."""
    p = _pending_state()
    key = (p["mtime_ns"], p["size"])
    text = (p.get("text") or "").strip()
    if text and key != ss.get("pending_seen"):
        ss["pending_seen"] = key
        if _new_text_arrived(text):
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


# --- Исходный текст (сразу под кнопкой закрыть, со скроллом) ------------------

if (ss["text"] or "").strip():
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

# --- Селекты: источник → приёмник ----------------------------------------------

c_src, c_arrow, c_tgt = st.columns([20, 2, 20], vertical_alignment="center", gap="small")
with c_src:
    st.selectbox(
        "С",
        SOURCE_OPTIONS,
        key="source_lang_name",
        label_visibility="collapsed",
        on_change=lambda: (
            ss.update(source_user_set=True, run_now=True) if ss.get("result") else None
        ),
    )
with c_arrow:
    st.markdown('<div class="mt-arrow">→</div>', unsafe_allow_html=True)
with c_tgt:
    st.selectbox(
        "На",
        TARGETS,
        index=TARGETS.index(q_target) if q_target in TARGETS else 0,
        key="target_lang_name",
        label_visibility="collapsed",
        on_change=lambda: ss.update(run_now=True) if ss.get("text") else None,
    )

# --- Перевод (запускается сам: новый текст или смена языка) ---------------------

if ss.pop("run_now", False) and (ss["text"] or "").strip():
    src = ss["source_lang_name"]
    payload = {
        "text": ss["text"],
        "src": "auto" if src == "Авто" else src,
        "tgt": ss["target_lang_name"],
    }
    # Фиксированная высота: стриминг не наезжает на исходник и скроллится
    with st.container(height=216, border=False):
        box = st.empty()
        acc: list[str] = []
        for event, data in sse_events(payload):
            if event == "status":
                box.markdown(f"⏳ _{STATUS_LABELS.get(data.get('phase'), data.get('phase', '…'))}_")
            elif event == "detect":
                ss["detected"] = data
                if data.get("used_as_source"):
                    ss["src_detected_name"] = data["used_as_source"]
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
    with st.container(height=216, border=False):
        st.markdown(
            f'<div class="mt-translation">{html.escape(ss["result"])}</div>',
            unsafe_allow_html=True,
        )

_poll_pending()
