import Foundation
import WebKit

/// Раздаёт встроенный в бандл фронтенд (frontend/dist, собран в один
/// index.html через vite-plugin-singlefile) по схеме app://.
/// UI не зависит ни от какого HTTP-сервера; данные приходят по WebSocket.
final class AppSchemeHandler: NSObject, WKURLSchemeHandler {
    static let scheme = "app"

    /// Bundle.main при прямом запуске бинарника резолвится в …/Contents,
    /// поэтому проверяем оба варианта и берём существующий.
    static func frontendDirectory() -> URL? {
        let exe = URL(fileURLWithPath: CommandLine.arguments[0]).resolvingSymlinksInPath()
        let fromExe = exe
            .deletingLastPathComponent() // MacOS
            .deletingLastPathComponent() // Contents
            .appendingPathComponent("Resources")
            .appendingPathComponent("frontend")
        let fromBundle = Bundle.main.resourceURL?.appendingPathComponent("frontend")
        let index = "index.html"
        for url in [fromBundle, fromExe].compactMap({ $0 }) {
            if FileManager.default.fileExists(atPath: url.appendingPathComponent(index).path) {
                return url
            }
        }
        return nil
    }

    private let mimeTypes: [String: String] = [
        "html": "text/html; charset=utf-8",
        "js": "text/javascript; charset=utf-8",
        "css": "text/css; charset=utf-8",
        "svg": "image/svg+xml",
        "png": "image/png",
        "json": "application/json",
        "woff2": "font/woff2",
    ]

    func webView(
        _ webView: WKWebView, start urlSchemeTask: WKURLSchemeTask
    ) {
        let url = urlSchemeTask.request.url ?? URL(string: "app://bundle/index.html")!
        let path = url.path.isEmpty || url.path == "/" ? "/index.html" : url.path
        let name = String(path.dropFirst())

        guard let base = Self.frontendDirectory(),
            name.range(of: #"^\w[\w./-]*$"#, options: .regularExpression) != nil,
            !name.contains("..")
        else {
            urlSchemeTask.didFailWithError(URLError(.badURL))
            return
        }
        let fileURL = base.appendingPathComponent(name)
        guard
            fileURL.standardizedFileURL.path.hasPrefix(base.standardizedFileURL.path),
            let data = try? Data(contentsOf: fileURL)
        else {
            urlSchemeTask.didFailWithError(URLError(.fileDoesNotExist))
            return
        }
        let ext = (name as NSString).pathExtension.lowercased()
        let mime = mimeTypes[ext] ?? "application/octet-stream"
        let response = HTTPURLResponse(
            url: url, statusCode: 200, httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": mime, "Cache-Control": "no-cache"])!
        urlSchemeTask.didReceive(response)
        urlSchemeTask.didReceive(data)
        urlSchemeTask.didFinish()
    }

    func webView(
        _ webView: WKWebView, stop urlSchemeTask: WKURLSchemeTask
    ) {}
}
