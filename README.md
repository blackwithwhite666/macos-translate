# macos-translate

Локальный переводчик для macOS: выделил текст → нажал «Перевести» → рядом с курсором
появилось аккуратное окошко со стримящимся переводом + карточка из системного словаря
при наведении на слово. Всё офлайн, ничего не уходит с машины.

```
Выделение → Quick Action → macos-translate:// → NSPanel + WKWebView (Swift)
                                   │
                                   ▼
              Streamlit-панель (:8502) — UI, стриминг
                                   │  HTTP (SSE)
                                   ▼
              gateway FastAPI (:8765) — ручки, lingua-детект, логи
                                   │  spawn/terminate по простою
                                   ▼
              подпроцесс worker.py — TranslateGemma 4B (MLX), ~4 ГБ
```

## Состав

| Слой | Что делает |
|---|---|
| `app/` — Swift | `NSPanel` + `WKWebView`, URL-scheme `macos-translate://`, автозапуск сервера, карточка из системных словарей (`DCSCopyTextDefinition`) |
| `server/gateway.py` | `GET /health`, `POST /detect` (lingua), `POST /translate` (SSE-стриминг); держит модель в подпроцессе и **выгружает её после 10 минут простоя** |
| `server/worker.py` | Подпроцесс с моделью (JSONL по stdio); EOF на stdin = выгрузка |
| `server/panel_app.py` | Компактная Streamlit-панель: авто-детект языка, стриминг токенов, копирование |

Модель — `mlx-community/translategemma-4b-it-8bit` (~4 ГБ), кэшируется в
`~/.cache/huggingface/hub` при первом переводе. Промпт — как в
[translategemma-studio](https://github.com/darylalim/translategemma-studio).

## Установка

```bash
cd ~/projects/macos-translate/server && uv sync      # зависимости Python
cd ~/projects/macos-translate/app && ./build.sh      # соберёт build/MacOSTranslate.app
~/projects/macos-translate/scripts/install-launchd.sh  # LaunchAgent: сервер живёт всегда
open ~/projects/macos-translate/app/build/MacOSTranslate.app
```

Требования: Apple Silicon, macOS 13+, Python 3.12+ (`uv`), ~4 ГБ на модель.

### Quick Action (выделение → перевод)

1. **Automator** → New → **Quick Action**
2. «Service receives selected **text** in **any application**»
3. Добавьте **Run Shell Script**, «Pass input: **to stdin**», содержимое — `scripts/quick-action.sh` (одна строка: `~/projects/macos-translate/scripts/quick-action.sh "$@"`)
4. Сохраните как «Перевести»
5. Хоткей: System Settings → Keyboard → Keyboard Shortcuts → Services → «Перевести» (например ⌥⌘T)

Проверка вручную:

```bash
echo "Hello, world" | ~/projects/macos-translate/scripts/quick-action.sh
```

## Логи

- `logs/translations.jsonl` — что просили перевести и что перевёл (вход, выход,
  языки, токены, длительность). Смотреть: `tail -f logs/translations.jsonl`
- `logs/server.log` — жизненный цикл: подъём/выгрузка модели, ошибки

## Память

- Простой: только gateway (~60–200 МБ; lingua подгружается лениво). Модель **выгружена**.
- Запрос: spawn воркера (~5–10 с с тёплым кэшем) → +4 ГБ на время переводов →
  через 10 минут без запросов — выгрузка (проверка каждые 15 с).

Переменные окружения (LaunchAgent или запуск вручную):

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `MT_IDLE_TIMEOUT` | `600` | секунд простоя до выгрузки модели |
| `MT_API` | `http://127.0.0.1:8765` | адрес gateway для панели |
| `MT_DEFAULT_TARGET` | `Russian` | целевой язык по умолчанию |

## Словарь

Наведение на слово в готовом переводе показывает статью из **активных** словарей
Dictionary.app (Oxford и т.д. — управляются в настройках Dictionary.app, включая
скачивание дополнительных). Слово ищется в контексте фразы, поэтому словоформы
(«went» → «go») находятся корректно.

## Тесты

```bash
cd server && uv run pytest          # gateway + фейковый воркер, модель не нужна
```

Живой прогон модели:

```bash
curl -N -X POST http://127.0.0.1:8765/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hello, how are you?","src":"auto","tgt":"Russian"}'
```

## Остановка

```bash
~/projects/macos-translate/scripts/stop-servers.sh      # разово
~/projects/macos-translate/scripts/uninstall-launchd.sh # удалить LaunchAgent
```

## Лицензия

Код — MIT. `server/languages.py` — из translategemma-studio (MIT). Модель
TranslateGemma — Google Gemma Terms of Use.
