/// Инжектится в WKWebView на каждый документ:
/// — карточка словаря снизу (появляется только при наведении на слово);
/// — наведение на слово в .mt-source / .mt-translation → сообщение "lookup" в Swift.
/// Границы слова считаются по Unicode-свойствам (работает для кириллицы, CJK и
/// т.д.), подсветка — CSS Custom Highlight API, без мутаций DOM.
enum PageScript {
    static let source = #"""
    (function () {
      if (window.__mtInstalled) return; window.__mtInstalled = true;

      var css = [
        '#mtCard{position:fixed;left:8px;right:8px;bottom:8px;min-height:96px;max-height:136px;',
        'background:rgba(28,30,38,.98);border:1px solid rgba(255,255,255,.16);border-radius:11px;',
        'padding:8px 11px;color:#e8e8ec;z-index:2147483000;opacity:0;pointer-events:none;',
        'transform:translateY(6px);transition:opacity .12s,transform .12s;',
        'box-shadow:0 6px 24px rgba(0,0,0,.45);font-size:12px}',
        '#mtCard.mt-on{opacity:1;pointer-events:auto;transform:none}',
        '#mtHead{display:flex;justify-content:space-between;align-items:center;margin-bottom:3px}',
        '#mtWord{font-weight:700;font-size:13.5px}',
        '#mtCopy{cursor:pointer;opacity:.5;font-size:14px;padding:0 3px}',
        '#mtCopy:hover{opacity:1}',
        '#mtBody{line-height:1.45;max-height:88px;overflow-y:auto;color:#c9c9d1}',
        '::highlight(mt-word){background-color:rgba(122,162,255,.45);border-radius:2px}',
        '.block-container{padding:.55rem .85rem .6rem !important;max-width:none !important}',
        '[data-testid="stVerticalBlock"]{gap:.5rem !important}',
        '[data-testid="stHeader"],#stDecoration,[data-testid="stStatusWidget"]{display:none !important}',
        '.stButton>button{height:2.05rem;font-size:.85rem;margin:0 !important}',
        'div[data-baseweb="select"]>div{min-height:1.9rem;font-size:.85rem}',
        '.stApp{background:#1c1e24}'
      ].join('');
      var st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);

      var card = document.createElement('div'); card.id = 'mtCard';
      card.innerHTML = '<div id="mtHead"><span id="mtWord"></span>'
        + '<span id="mtCopy" title="Скопировать перевод">&#10696;</span></div>'
        + '<div id="mtBody"></div>';
      document.body.appendChild(card);
      var bodyEl = document.getElementById('mtBody');
      var wordEl = document.getElementById('mtWord');

      document.getElementById('mtCopy').addEventListener('click', function () {
        var t = document.querySelector('.mt-translation');
        if (t && navigator.clipboard) navigator.clipboard.writeText(t.textContent);
      });

      window.MtDict = {
        show: function (word, html) {
          wordEl.textContent = word;
          bodyEl.innerHTML = html;
          card.classList.add('mt-on');
        },
        hide: function () {
          card.classList.remove('mt-on');
        }
      };

      var lastWord = null, lastAt = 0;

      function hideAll() {
        lastWord = null;
        if (window.CSS && CSS.highlights) CSS.highlights.delete('mt-word');
        MtDict.hide();
      }

      function isWordChar(c) { return /[\p{L}\p{M}\p{N}]/u.test(c); }
      function isJoinChar(c) { return c === '-' || c === '\u2019' || c === '\''; }

      function wordAt(text, i) {
        if (i < 0 || i >= text.length) return null;
        if (!isWordChar(text[i])) {
          if (i + 1 < text.length && isWordChar(text[i + 1])) i += 1;
          else return null;
        }
        var s = i, e = i + 1;
        while (s > 0 && isWordChar(text[s - 1])) s -= 1;
        while (s > 0 && isJoinChar(text[s - 1]) && s > 1 && isWordChar(text[s - 2])) s -= 1;
        while (e < text.length && isWordChar(text[e])) e += 1;
        while (e < text.length && isJoinChar(text[e]) && e + 1 < text.length && isWordChar(text[e + 1])) e += 1;
        return [s, e, text.slice(s, e)];
      }

      function offsetIn(zone, node, off) {
        var walker = document.createTreeWalker(zone, NodeFilter.SHOW_TEXT);
        var n, acc = 0;
        while ((n = walker.nextNode())) {
          if (n === node) return acc + off;
          acc += n.textContent.length;
        }
        return null;
      }

      function highlight(zone, s, e) {
        try {
          if (!window.Highlight || !window.CSS || !CSS.highlights) return;
          var walker = document.createTreeWalker(zone, NodeFilter.SHOW_TEXT);
          var n, acc = 0, sNode = null, sOff = 0, eNode = null, eOff = 0;
          while ((n = walker.nextNode())) {
            var len = n.textContent.length;
            if (sNode === null && s < acc + len) { sNode = n; sOff = s - acc; }
            if (e <= acc + len) { eNode = n; eOff = e - acc; break; }
            acc += len;
          }
          if (!sNode || !eNode) return;
          var range = document.createRange();
          range.setStart(sNode, sOff);
          range.setEnd(eNode, eOff);
          CSS.highlights.set('mt-word', new Highlight(range));
        } catch (err) { /* подсветка не критична */ }
      }

      document.addEventListener('mousemove', function (ev) {
        var el = ev.target;
        var zone = el && el.closest ? el.closest('.mt-source, .mt-translation') : null;
        if (!zone) { hideAll(); return; }
        var now = Date.now();
        if (now - lastAt < 50) return;
        lastAt = now;

        var r = document.caretRangeFromPoint(ev.clientX, ev.clientY);
        if (!r || !zone.contains(r.startContainer)) { hideAll(); return; }
        var text = zone.textContent;
        var off = offsetIn(zone, r.startContainer, r.startOffset);
        if (off == null) return;
        var hit = wordAt(text, off);
        if (!hit) { hideAll(); return; }
        if (hit[2] === lastWord) return;   // то же слово — не дёргаем Swift
        lastWord = hit[2];
        highlight(zone, hit[0], hit[1]);
        MtDict.show(lastWord, '<i style="opacity:.55">ищу…</i>');
        window.webkit.messageHandlers.lookup.postMessage(
          { word: lastWord, context: text, start: hit[0], end: hit[1] });
      });
    })();
    """#
}
