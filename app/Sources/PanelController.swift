import AppKit
import WebKit

/// Прокси, чтобы WKUserContentController не удерживал PanelController вечно.
final class WeakScriptMessageHandler: NSObject, WKScriptMessageHandler {
    weak var delegate: WKScriptMessageHandler?
    init(_ delegate: WKScriptMessageHandler) { self.delegate = delegate }
    func userContentController(
        _ userContentController: WKUserContentController, didReceive message: WKScriptMessage
    ) {
        delegate?.userContentController(userContentController, didReceive: message)
    }
}

final class PanelController:
    NSObject, NSWindowDelegate, WKScriptMessageHandler, WKNavigationDelegate {
    static let pendingPath = NSHomeDirectory() + "/.local/state/macos-translate/pending.txt"
    static let panelURL = URL(string: "http://127.0.0.1:8502/")!

    private var panel: NSPanel?
    private var webView: WKWebView?
    private var streamlitLoaded = false
    private static let dcsQueue = DispatchQueue(label: "local.macos-translate.dcs")

    static func readPendingText() -> String? {
        guard let s = try? String(contentsOfFile: pendingPath, encoding: .utf8) else { return nil }
        let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
        return t.isEmpty ? nil : t
    }

    func hide() {
        panel?.orderOut(nil)
    }

    /// Показать панель. Если страница уже открыта — просто показываем её:
    /// новый текст панель подхватит сама (GET /pending), без перезагрузки.
    func present(text: String?, target: String?) {
        let panel = ensurePanel()
        position(panel)
        panel.orderFrontRegardless()
        NSApp.activate(ignoringOtherApps: true)
        panel.makeKey()

        guard !streamlitLoaded else { return } // быстрый путь: ничего не грузим

        var comps = URLComponents(url: Self.panelURL, resolvingAgainstBaseURL: false)!
        var items = [URLQueryItem(
            name: "t", value: String(Int(Date().timeIntervalSince1970 * 1000)))]
        if let text, !text.isEmpty {
            items.append(URLQueryItem(name: "text", value: String(text.prefix(8000))))
        }
        if let target, !target.isEmpty {
            items.append(URLQueryItem(name: "target", value: target))
        }
        comps.queryItems = items

        ServerManager.shared.ensureRunning { [weak self] ok in
            guard let self, let url = comps.url else { return }
            if ok {
                self.webView?.load(URLRequest(url: url))
            } else {
                self.streamlitLoaded = false
                self.webView?.loadHTMLString(Self.errorHTML, baseURL: nil)
            }
        }
    }

    private func ensurePanel() -> NSPanel {
        if let panel { return panel }

        let panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 460, height: 580),
            styleMask: [.titled, .closable, .resizable, .fullSizeContentView],
            backing: .buffered, defer: false)
        panel.title = "Перевод"
        panel.titleVisibility = .hidden
        panel.titlebarAppearsTransparent = true
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.hidesOnDeactivate = true // клик мимо — панель исчезает, как словарь
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.backgroundColor = NSColor(srgbRed: 0.11, green: 0.118, blue: 0.141, alpha: 1)
        panel.isReleasedWhenClosed = false
        panel.delegate = self
        panel.minSize = NSSize(width: 380, height: 460)
        panel.standardWindowButton(.miniaturizeButton)?.isHidden = true
        panel.standardWindowButton(.zoomButton)?.isHidden = true

        let config = WKWebViewConfiguration()
        let ucc = config.userContentController
        ucc.add(WeakScriptMessageHandler(self), name: "lookup")
        ucc.addUserScript(
            WKUserScript(
                source: PageScript.source, injectionTime: .atDocumentEnd,
                forMainFrameOnly: true))

        let webView = WKWebView(
            frame: NSRect(x: 0, y: 0, width: 460, height: 580), configuration: config)
        webView.navigationDelegate = self
        webView.underPageBackgroundColor = NSColor(
            srgbRed: 0.11, green: 0.118, blue: 0.141, alpha: 1)
        panel.contentView = webView

        self.webView = webView
        self.panel = panel
        return panel
    }

    /// Панель появляется рядом с курсором (где выделяли текст), в пределах экрана.
    private func position(_ panel: NSPanel) {
        let mouse = NSEvent.mouseLocation
        let screen = NSScreen.screens.first { NSMouseInRect(mouse, $0.frame, false) } ?? NSScreen.main
        guard let visible = screen?.visibleFrame else { return }
        let size = CGSize(
            width: min(460, visible.width - 24), height: min(580, visible.height - 24))
        panel.setFrame(NSRect(x: 0, y: 0, width: size.width, height: size.height), display: false)
        var x = mouse.x - 24
        var y = mouse.y - size.height - 18
        if y < visible.minY + 12 { y = mouse.y + 22 }
        x = max(visible.minX + 10, min(x, visible.maxX - size.width - 10))
        y = max(visible.minY + 10, min(y, visible.maxY - size.height - 10))
        panel.setFrameOrigin(NSPoint(x: x, y: y))
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        sender.orderOut(nil) // прячем, приложение продолжает жить
        return false
    }

    // MARK: WKNavigationDelegate

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        if let url = webView.url, url.host == "127.0.0.1", url.port == 8502 {
            streamlitLoaded = true
        }
    }

    // MARK: WKScriptMessageHandler — слово под курсором

    func userContentController(
        _ userContentController: WKUserContentController, didReceive message: WKScriptMessage
    ) {
        guard
            message.name == "lookup",
            let body = message.body as? [String: Any],
            let word = body["word"] as? String,
            let context = body["context"] as? String
        else { return }
        let start = (body["start"] as? NSNumber)?.intValue ?? 0
        let end = (body["end"] as? NSNumber)?.intValue ?? 0

        // DCS может подтормаживать на первом запросе — уводим с главного потока
        Self.dcsQueue.async { [weak self] in
            let html = DictLookup.definitionHTML(
                word: word, context: context, start: start, end: end)
            DispatchQueue.main.async {
                self?.showInCard(word: word, html: html)
            }
        }
    }

    private func showInCard(word: String, html: String) {
        guard let webView,
            let data = try? JSONSerialization.data(withJSONObject: [word, html]),
            let arr = String(data: data, encoding: .utf8)
        else { return }
        // arr == ["слово","<html>"] — срезаем скобки, получаем валидные JS-литералы
        let args = String(arr.dropFirst().dropLast())
        webView.evaluateJavaScript(
            "window.MtDict && MtDict.show(\(args));", completionHandler: nil)
    }

    static let errorHTML = """
        <html><head><style>
        body{font-family:-apple-system;background:#1c1e24;color:#e8e8ec;display:flex;
        align-items:center;justify-content:center;height:100vh;margin:0}
        code{background:rgba(255,255,255,.08);padding:2px 6px;border-radius:5px;font-size:12px}
        </style></head><body><div style="text-align:center;max-width:340px">
        <div style="font-size:40px">⚠️</div>
        <h3>Сервер перевода не отвечает</h3>
        <p style="opacity:.7;font-size:13px">Установите сервис и повторите:<br>
        <code>~/projects/macos-translate/scripts/install-launchd.sh</code></p>
        </div></body></html>
        """
}
