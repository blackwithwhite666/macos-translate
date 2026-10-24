import AppKit

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var panelController: PanelController?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let controller = PanelController()
        panelController = controller

        // macos-translate://translate?text=…&target=… (Apple Event GURL)
        NSAppleEventManager.shared().setEventHandler(
            self,
            andSelector: #selector(handleGetURL(_:withReplyEvent:)),
            forEventClass: AEEventClass(kInternetEventClass),
            andEventID: AEEventID(kAEGetURL))

        // Esc — спрятать панель
        NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            if event.keyCode == 53 {
                self?.panelController?.hide()
                return nil
            }
            return event
        }

        // Ручной запуск (без URL) — показать панель сразу
        controller.present(text: nil, target: nil)
    }

    @objc private func handleGetURL(
        _ event: NSAppleEventDescriptor, withReplyEvent: NSAppleEventDescriptor
    ) {
        guard
            let raw = event.paramDescriptor(forKeyword: keyDirectObject)?.stringValue,
            let url = URL(string: raw),
            url.scheme?.lowercased() == "macos-translate",
            (url.host ?? "").lowercased() == "translate"
        else { return }

        var params: [String: String] = [:]
        if let comps = URLComponents(url: url, resolvingAgainstBaseURL: false) {
            for item in comps.queryItems ?? [] {
                params[item.name] = item.value ?? ""
            }
        }
        var text = params["text"]
        if text == nil || text!.isEmpty {
            // Quick Action кладёт выделенный текст в файл, чтобы не кодировать
            // его в URL (многострочность, unicode и т.д.)
            text = PanelController.readPendingText()
        }
        panelController?.present(text: text, target: params["target"])
    }
}
