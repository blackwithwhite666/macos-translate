import Foundation
import CoreServices

/// Статьи из системных словарей macOS (те же, что в Dictionary.app и Look Up).
enum DictLookup {
    /// DCS смотрит слово в контексте всей фразы — учитывает словоформы
    /// («went» найдёт «go»). start/end — границы слова в UTF-16, как в JS.
    static func definitionHTML(word: String, context: String, start: Int, end: Int) -> String {
        let nsContext = context as NSString
        let loc = max(0, min(start, nsContext.length))
        let len = max(0, min(end, nsContext.length) - loc)
        var definition: String?
        if len > 0 {
            let cf = DCSCopyTextDefinition(nil, nsContext as CFString, CFRange(location: loc, length: len))
            if let cf {
                definition = cf.takeRetainedValue() as String
            }
        }
        return format(word: word, definition: definition)
    }

    private static func format(word: String, definition: String?) -> String {
        guard let definition, !definition.isEmpty else {
            return "<i style=\"opacity:.55\">нет статьи в словаре для «\(escape(word))»</i>"
        }
        // DCS склеивает статьи нескольких словарей через " | " — оформим каждую
        // отдельным блоком с разделителем.
        let entries = definition.components(separatedBy: " | ")
        var html = ""
        for (i, entry) in entries.enumerated() {
            let body = escape(entry).replacingOccurrences(of: "\n", with: "<br>")
            if i > 0 {
                html += "<div style=\"margin-top:8px;padding-top:6px;"
                    + "border-top:1px solid rgba(255,255,255,.12)\"></div>"
            }
            html += "<div>\(body)</div>"
        }
        return html
    }

    private static func escape(_ s: String) -> String {
        s.replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
    }
}
