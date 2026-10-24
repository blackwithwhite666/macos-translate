# macos-translate

Локальный переводчик для macOS: выделили текст → нажали «Перевести» → рядом с курсором
появилось окошко, в котором перевод **печатается построчно**. Наведение на слово —
статья из системного словаря. Всё офлайн: ни один байт не уходит с машины.

| | |
|---|---|
| Модель | Google TranslateGemma 4B, 8-битный MLX-квант (~4 ГБ) |
| Языки | 295 (225 двунаправленных + 70 «с английского») |
| Детект языка | lingua-language-detector (авто) |
| Словарь | системные словари macOS (Dictionary.app / «Локатор») |
| Память | модель живёт в подпроцессе и **выгружается после 10 минут простоя** |

## Как это устроено

```
Выделение текста
   │  Quick Action (Automator) пишет текст в файл и открывает macos-translate://
   ▼
MacOSTranslate.app — нативная оболочка (Swift, без иконки в Dock)
   │  NSPanel + WKWebView; UI — ОДИН минифицированный index.html, вшитый в бандл
   │  (TypeScript + Bootstrap, собирается Vite), грузится по схеме app://
   ▼
WebSocket → gateway на FastAPI (порт 8765, живёт в launchd)
   │  пушит новый выделенный текст, стримит токены перевода
   ▼
подпроцесс worker.py — TranslateGemma через MLX (~4 ГБ, выгрузка по простою)
```

Управление: `https://github.com/blackwithwhite666/macos-translate`

## Установка

Нужны: Mac на Apple Silicon, macOS 13+, [uv](https://docs.astral.sh/uv/), Node.js (для сборки UI), Xcode Command Line Tools (`xcode-select --install`).

```bash
git clone https://github.com/blackwithwhite666/macos-translate.git
cd macos-translate

# 1) Python-зависимости сервера
cd server && uv sync && cd ..

# 2) Собрать приложение (UI + Swift, на выходе app/build/MacOSTranslate.app)
app/build.sh

# 3) Сервис перевода: старт при входе, автоперезапуск, модель по требованию
scripts/install-launchd.sh

# 4) Запустить приложение
open app/build/MacOSTranslate.app
```

При первом переводе модель скачается с Hugging Face (3,9 ГБ) в
`~/.cache/huggingface` — первый перевод займёт пару минут, дальше ~5–10 с
холодного старта модели и 1–3 с с тёплой.

> Приложение можно скопировать в `/Applications` или `~/Applications` —
> оно самодостаточно, сервер нужен только для переводов.

## Автоматизация: перевод выделенного текста

### Quick Action (контекстное меню + хоткей)

1. Откройте **Automator** → File → New → **Quick Action**
2. Вверху: «Workflow receives selected **text** in **any application**»
3. Добавьте действие **Run Shell Script**:
   - Shell: `/bin/zsh`, «Pass input»: **to stdin**
   - содержимое — одна строка:
     ```bash
     ~/projects/macos-translate/scripts/quick-action.sh "$@"
     ```
4. Сохраните как **«Перевести»**

Проверка из терминала:

```bash
echo "Hello, world" | ~/projects/macos-translate/scripts/quick-action.sh
```

### Горячая клавиша

System Settings → Keyboard → Keyboard Shortcuts → **Services** → «Перевести» →
Add Shortcut. Свободное сочетание: **⌥⌘E** (⌥⌘R и ⌥⌘U тоже свободны).

После настройки: выделили текст → правый клик → Службы → «Перевести»
(или ⌥⌘E) → панель с переводом рядом с курсором.

Целевой язык по умолчанию русский; смените в селекте панели — выбор
запоминается. Скрипту можно передать другой язык:
`quick-action.sh English`.

## Использование

- **Панель**: клик мимо — прячется, Esc — тоже; тянется за заголовок; перевод
  печатается с мигающей кареткой, длинные тексты скроллятся
- **Словарь**: наведите курсор на слово в исходнике или переводе — снизу
  карточка со статьёй из активных словарей (управляются в Dictionary.app);
  слово ищется в контексте фразы, словоформы («went» → «go») находятся
- **Исходный язык**: «Авто» (lingua) — после детекта селект подставит язык;
  выбор языка вручную мгновенно перезапускает перевод
- **Копирование**: ⧉ в карточке словаря или просто Cmd+C по выделенному

## Логи

- `logs/translations.jsonl` — что просили перевести и что перевёл: вход, выход,
  языки, токены, длительность (`tail -f logs/translations.jsonl`)
- `logs/server.log` — жизненный цикл: подъём/выгрузка модели, ошибки

## Настройка

Переменные окружения LaunchAgent (`~/Library/LaunchAgents/local.macos-translate.server.plist`):

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `MT_IDLE_TIMEOUT` | `600` | секунд простоя до выгрузки модели |
| `MT_DEFAULT_TARGET` | `Russian` | целевой язык по умолчанию |

Порты: gateway `127.0.0.1:8765` (HTTP+SSE+WebSocket). UI ничего не слушает.

После правок plist: `launchctl kickstart -k gui/$(id -u)/local.macos-translate.server`.

## Разработка

```bash
cd server
uv run pytest            # тесты (фейковый воркер, модель не нужна)
uv run ruff check .      # линт
uv run ty check gateway.py worker.py   # типы

cd ../frontend
npm run typecheck        # TypeScript

cd ../app
./build.sh               # пересборка UI + Swift + бандл
```

Ручная проверка перевода без UI:

```bash
curl -N -X POST http://127.0.0.1:8765/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hello, how are you?","src":"auto","tgt":"Russian"}'
```

### Структура

```
app/        Swift: NSPanel+WKWebView, app://-схема, словарный мост (DCS)
frontend/   TypeScript-UI (Vite → один index.html в бандл приложения)
server/     FastAPI-gateway + worker.py с моделью, тесты
scripts/    quick-action.sh, install/uninstall-launchd.sh, gen-languages.py
logs/       translations.jsonl, server.log
```

## Остановка и удаление

```bash
scripts/stop-servers.sh       # разово остановить серверы
scripts/uninstall-launchd.sh  # удалить LaunchAgent
# приложение: просто закрыть/удалить MacOSTranslate.app
```

## Лицензия

Код — MIT. Модель TranslateGemma — Google Gemma Terms of Use
(скачивается отдельно при первом запуске).
