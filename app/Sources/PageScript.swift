/// Инжектится в WKWebView на каждый документ:
/// — карточка словаря внизу окна (поверх Streamlit);
/// — наведение на слово в .mt-translation → сообщение "lookup" в Swift.
enum PageScript {
    static let source = #"""
    (function () {
      if (window.__mtInstalled) return; window.__mtInstalled = true;

      var css = [
        '#mtCard{position:fixed;left:10px;right:10px;bottom:10px;min-height:118px;max-height:150px;',
        'background:rgba(30,32,40,.97);border:1px solid rgba(255,255,255,.14);border-radius:12px;',
        'padding:10px 12px;color:#e8e8ec;z-index:2147483000;opacity:0;transition:opacity .15s;',
        'backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);font-size:12px}',
        '#mtCard.mt-on{opacity:1}',
        '#mtHead{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}',
        '#mtWord{font-weight:700;font-size:14px}',
        '#mtCopy{cursor:pointer;opacity:.55;font-size:14px}',
        '#mtCopy:hover{opacity:1}',
        '#mtBody{line-height:1.5;max-height:104px;overflow-y:auto;color:#c9c9d1}',
        '.mt-hl{background:rgba(122,162,255,.38);border-radius:3px}',
        '.block-container{padding-bottom:175px !important}',
        '[data-testid="stHeader"],#stDecoration,[data-testid="stStatusWidget"]{display:none !important}'
      ].join('');
      var st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);

      var card = document.createElement('div'); card.id = 'mtCard';
      card.innerHTML = '<div id="mtHead"><span id="mtWord"></span>'
        + '<span id="mtCopy" title="Скопировать перевод">&#10696;</span></div>'
        + '<div id="mtBody">Наведите курсор на слово перевода — покажу словарную статью</div>';
      document.body.appendChild(card);
      var bodyEl = document.getElementById('mtBody');
      var wordEl = document.getElementById('mtWord');
      card.classList.add('mt-on');

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
        reset: function () {
          wordEl.textContent = '';
          bodyEl.textContent = 'Наведите курсор на слово перевода — покажу словарную статью';
        }
      };

      var curSpan = null, lastWord = null, lastAt = 0;
      function unwrap() {
        if (curSpan && curSpan.parentNode) {
          curSpan.parentNode.replaceChild(document.createTextNode(curSpan.textContent), curSpan);
          if (curSpan.parentNode) curSpan.parentNode.normalize();
        }
        curSpan = null;
      }

      document.addEventListener('mousemove', function (e) {
        var el = e.target;
        var t = el && el.closest ? el.closest('.mt-translation') : null;
        if (!t) { lastWord = null; return; }
        var now = Date.now();
        if (now - lastAt < 120) return;

        var r = document.caretRangeFromPoint(e.clientX, e.clientY);
        if (!r || !t.contains(r.startContainer)) return;

        var sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(r.cloneRange());
        sel.modify('extend', 'forward', 'word');
        sel.modify('extend', 'backward', 'word');
        var word = (sel.toString() || '').trim();
        if (!word || word.length > 48 || /\s/.test(word)) { sel.removeAllRanges(); return; }

        var wr = sel.getRangeAt(0);
        var pre = document.createRange();
        pre.selectNodeContents(t);
        pre.setEnd(wr.startContainer, wr.startOffset);
        var start = pre.toString().length;
        var end = start + word.length;
        sel.removeAllRanges();
        lastAt = now;

        if (word !== lastWord) {
          lastWord = word;
          unwrap();
          try {
            var span = document.createElement('span');
            span.className = 'mt-hl';
            var range = document.createRange();
            range.setStart(wr.startContainer, wr.startOffset);
            range.setEnd(wr.endContainer, wr.endOffset);
            range.surroundContents(span);
            curSpan = span;
          } catch (err) { /* подсветка не критична */ }
          window.webkit.messageHandlers.lookup.postMessage(
            { word: word, context: t.textContent, start: start, end: end });
          MtDict.show(word, '<i style="opacity:.6">ищу…</i>');
        }
      });
    })();
    """#
}
