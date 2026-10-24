/** Наведение на слово в зоне → подсветка + статья из системного словаря
 * (через Swift-мост window.webkit.messageHandlers.lookup). */

const WORD_RE = /[\p{L}\p{M}\p{N}]/u;
const JOIN_CHARS = new Set(['-', '’', "'"]);

let lastWord: string | null = null;
let lastAt = 0;

function isWordChar(c: string): boolean {
  return WORD_RE.test(c);
}

/** [начало, конец, слово] в UTF-16 индексах (совпадают с NSString/JS). */
export function wordAt(text: string, i: number): [number, number, string] | null {
  if (i < 0 || i >= text.length) return null;
  if (!isWordChar(text[i])) {
    if (i + 1 < text.length && isWordChar(text[i + 1])) i += 1;
    else return null;
  }
  let s = i;
  let e = i + 1;
  while (s > 0 && isWordChar(text[s - 1])) s -= 1;
  while (s > 0 && JOIN_CHARS.has(text[s - 1]) && s > 1 && isWordChar(text[s - 2])) s -= 1;
  while (e < text.length && isWordChar(text[e])) e += 1;
  while (
    e < text.length &&
    JOIN_CHARS.has(text[e]) &&
    e + 1 < text.length &&
    isWordChar(text[e + 1])
  )
    e += 1;
  return [s, e, text.slice(s, e)];
}

/** Смещение узла внутри текста зоны (сумма длин предыдущих текстовых узлов). */
function offsetIn(zone: Element, node: Node, off: number): number | null {
  const walker = document.createTreeWalker(zone, NodeFilter.SHOW_TEXT);
  let acc = 0;
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (n === node) return acc + off;
    acc += n.textContent?.length ?? 0;
  }
  return null;
}

/** Подсветка через CSS Custom Highlight API — без мутаций DOM. */
function highlight(zone: Element, s: number, e: number): void {
  try {
    if (!('highlights' in CSS) || !window.Highlight) return;
    const walker = document.createTreeWalker(zone, NodeFilter.SHOW_TEXT);
    let acc = 0;
    let sNode: Text | null = null;
    let sOff = 0;
    let eNode: Text | null = null;
    let eOff = 0;
    for (let n = walker.nextNode() as Text | null; n; n = walker.nextNode() as Text | null) {
      const len = n.textContent?.length ?? 0;
      if (sNode === null && s < acc + len) {
        sNode = n;
        sOff = s - acc;
      }
      if (e <= acc + len) {
        eNode = n;
        eOff = e - acc;
        break;
      }
      acc += len;
    }
    if (!sNode || !eNode) return;
    const range = document.createRange();
    range.setStart(sNode, sOff);
    range.setEnd(eNode, eOff);
    CSS.highlights.set('mt-word', new Highlight(range));
  } catch {
    /* подсветка не критична */
  }
}

function hideAll(): void {
  lastWord = null;
  if ('highlights' in CSS) CSS.highlights.delete('mt-word');
  window.MtDict?.hide();
}

export function attachHover(zones: HTMLElement[]): void {
  document.addEventListener('mousemove', (ev) => {
    const target = ev.target as Element | null;
    const zone = target?.closest?.('.zone') as HTMLElement | null;
    if (!zone || !zones.includes(zone)) {
      hideAll();
      return;
    }
    const now = Date.now();
    if (now - lastAt < 50) return;
    lastAt = now;

    const caret = document.caretRangeFromPoint(ev.clientX, ev.clientY);
    if (!caret || !zone.contains(caret.startContainer)) {
      hideAll();
      return;
    }
    const text = zone.textContent ?? '';
    const off = offsetIn(zone, caret.startContainer, caret.startOffset);
    if (off === null) return;
    const hit = wordAt(text, off);
    if (!hit) {
      hideAll();
      return;
    }
    const [s, e, word] = hit;
    if (word === lastWord) return; // то же слово — не дёргаем Swift
    lastWord = word;
    highlight(zone, s, e);
    window.MtDict?.show(word, '<i style="opacity:.55">ищу…</i>');
    window.webkit?.messageHandlers?.lookup?.postMessage({
      word,
      context: text,
      start: s,
      end: e,
    });
  });
}
