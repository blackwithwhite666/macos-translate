import 'bootstrap/dist/css/bootstrap.min.css';
import './style.css';
import { ALL_TARGETS, SOURCES } from './languages';
import type { ClientMessage, ServerEvent } from './types';

const GATEWAY = 'ws://127.0.0.1:8765/ws';

const state = {
  text: '',
  result: '',
  src: 'auto',
  tgt: 'Russian',
  seq: 0,
  busy: false,
};

let ws: WebSocket | null = null;
let wsReady = false;

// --- DOM ----------------------------------------------------------------------

const $ = <T extends HTMLElement>(id: string): T => {
  const el = document.getElementById(id);
  if (!el) throw new Error(`#${id} не найден`);
  return el as T;
};
const srcBox = $<HTMLDivElement>('src-box');
const outBox = $<HTMLDivElement>('out-box');
const srcSel = $<HTMLSelectElement>('src-lang');
const tgtSel = $<HTMLSelectElement>('tgt-lang');
const dictCard = $<HTMLDivElement>('dict-card');
const dictWord = $<HTMLSpanElement>('dict-word');
const dictBody = $<HTMLDivElement>('dict-body');

const PLACEHOLDER = 'Выделите текст в любом приложении и вызовите «Перевести»…';
const STATUS_LABELS: Record<string, string> = {
  detecting: 'Определяю язык…',
  'loading-model': 'Подгружаю модель (первый запуск ~10 с)…',
  generating: 'Перевожу…',
};

// --- Мост к системному словарю (Swift: DCSCopyTextDefinition) ------------------

declare global {
  interface Window {
    MtDict?: { show(word: string, html: string): void; hide(): void };
    webkit?: {
      messageHandlers?: {
        lookup?: { postMessage(msg: unknown): void };
      };
    };
  }
}

window.MtDict = {
  show(word: string, html: string): void {
    dictWord.textContent = word;
    dictBody.innerHTML = html;
    dictCard.classList.add('on');
  },
  hide(): void {
    dictCard.classList.remove('on');
  },
};

$<HTMLSpanElement>('dict-close').addEventListener('click', () => window.MtDict?.hide());
$<HTMLSpanElement>('copy-btn').addEventListener('click', () => {
  if (state.result && navigator.clipboard) void navigator.clipboard.writeText(state.result);
});

// --- Селекты -------------------------------------------------------------------

function fillSelects(): void {
  srcSel.add(new Option('Авто', 'auto'));
  for (const name of SOURCES) srcSel.add(new Option(name, name));
  for (const name of ALL_TARGETS) tgtSel.add(new Option(name, name));
  tgtSel.value = state.tgt;
}

srcSel.addEventListener('change', () => {
  state.src = srcSel.value;
  if (state.text) translate();
});
tgtSel.addEventListener('change', () => {
  state.tgt = tgtSel.value;
  try {
    localStorage.setItem('mt.tgt', state.tgt);
  } catch {
    /* приватный режим WKWebView — не критично */
  }
  if (state.text) translate();
});

// --- Исходный текст --------------------------------------------------------------

function setSourceText(text: string): void {
  state.text = text;
  srcBox.classList.remove('placeholder');
  srcBox.textContent = text;
  srcBox.scrollTop = 0;
}

function showPlaceholder(): void {
  srcBox.classList.add('placeholder');
  srcBox.textContent = PLACEHOLDER;
}

/** Стриминг: держим перевод прокрученным в конец. */
function scrollOutToEnd(): void {
  outBox.scrollTop = outBox.scrollHeight;
}

// --- WebSocket -------------------------------------------------------------------

function connect(): void {
  ws = new WebSocket(GATEWAY);
  ws.onopen = () => {
    wsReady = true;
  };
  ws.onclose = () => {
    wsReady = false;
    setTimeout(connect, 1000);
  };
  ws.onerror = () => ws?.close();
  ws.onmessage = (ev: MessageEvent<string>) => {
    handleEvent(JSON.parse(ev.data) as ServerEvent);
  };
}

function send(msg: ClientMessage): void {
  if (wsReady && ws) ws.send(JSON.stringify(msg));
}

function handleEvent(ev: ServerEvent): void {
  if (ev.type === 'pending') {
    if (ev.text.trim() && ev.text !== state.text) {
      state.src = 'auto';
      srcSel.value = 'auto';
      setSourceText(ev.text);
      translate();
    }
    return;
  }
  if (ev.seq !== undefined && ev.seq !== state.seq) return; // устаревший ответ

  switch (ev.type) {
    case 'status':
      outBox.innerHTML = `<span class="text-secondary">⏳ ${STATUS_LABELS[ev.phase] ?? ev.phase}</span>`;
      scrollOutToEnd();
      break;
    case 'detect':
      if (srcSel.value === 'auto' && ev.used_as_source) {
        state.src = ev.used_as_source;
        srcSel.value = ev.used_as_source;
      }
      break;
    case 'token':
      outBox.textContent += ev.text;
      scrollOutToEnd();
      break;
    case 'done':
      state.result = ev.translation;
      state.busy = false;
      outBox.textContent = ev.translation;
      scrollOutToEnd();
      break;
    case 'error':
      state.busy = false;
      outBox.innerHTML = `<span class="text-danger">${ev.message}</span>`;
      break;
  }
}

function translate(): void {
  if (!state.text.trim()) return;
  state.seq += 1;
  state.busy = true;
  state.result = '';
  outBox.textContent = '';
  send({ type: 'translate', text: state.text, src: state.src, tgt: state.tgt, seq: state.seq });
}

// --- Старт -----------------------------------------------------------------------

const q = new URLSearchParams(location.search);
if (q.get('target')) state.tgt = q.get('target') as string;
if (q.get('text')) setSourceText(q.get('text') as string);
try {
  const saved = localStorage.getItem('mt.tgt');
  if (saved && !q.get('target')) state.tgt = saved;
} catch {
  /* ignore */
}
try {
  history.replaceState(null, '', '/');
} catch {
  /* opaque origin у app:// — параметры никуда не денутся, страница не перезагружается */
}

fillSelects();
showPlaceholder();
import('./hover').then((m) => m.attachHover([srcBox, outBox]));
connect();
if (state.text) translate();
