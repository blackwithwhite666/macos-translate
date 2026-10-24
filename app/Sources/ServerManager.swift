import Foundation

/// Следит, что локальный сервер перевода (gateway :8765) жив.
/// Порядок: health → launchctl kickstart (LaunchAgent) → прямой запуск run.sh.
final class ServerManager {
    static let shared = ServerManager()
    private var fallbackProcess: Process?

    static var repoPath: String {
        if let env = ProcessInfo.processInfo.environment["MT_HOME"] { return env }
        return NSHomeDirectory() + "/projects/macos-translate"
    }

    private func isHealthy() -> Bool {
        guard let url = URL(string: "http://127.0.0.1:8765/health") else { return false }
        var req = URLRequest(url: url)
        req.timeoutInterval = 1.5
        let sem = DispatchSemaphore(value: 0)
        var ok = false
        URLSession.shared.dataTask(with: req) { _, resp, _ in
            if let http = resp as? HTTPURLResponse, http.statusCode == 200 { ok = true }
            sem.signal()
        }.resume()
        return sem.wait(timeout: .now() + 2) == .success && ok
    }

    func ensureRunning(completion: @escaping (Bool) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async { [self] in
            if isHealthy() {
                DispatchQueue.main.async { completion(true) }
                return
            }
            // 1) LaunchAgent (ставится scripts/install-launchd.sh)
            let kick = Process()
            kick.executableURL = URL(fileURLWithPath: "/bin/zsh")
            kick.arguments = [
                "-c",
                "launchctl kickstart gui/$(id -u)/local.macos-translate.server 2>/dev/null || true",
            ]
            try? kick.run()
            kick.waitUntilExit()

            if waitHealthy(timeout: 30) {
                DispatchQueue.main.async { completion(true) }
                return
            }
            // 2) фолбэк — запустить run.sh напрямую
            if fallbackProcess == nil {
                let p = Process()
                p.executableURL = URL(fileURLWithPath: "/bin/zsh")
                p.arguments = ["-lc", Self.repoPath + "/server/run.sh"]
                p.currentDirectoryURL = URL(fileURLWithPath: Self.repoPath)
                do {
                    try p.run()
                    fallbackProcess = p
                } catch {
                    DispatchQueue.main.async { completion(false) }
                    return
                }
            }
            let ok = waitHealthy(timeout: 45)
            DispatchQueue.main.async { completion(ok) }
        }
    }

    private func waitHealthy(timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if isHealthy() { return true }
            Thread.sleep(forTimeInterval: 0.7)
        }
        return false
    }
}
