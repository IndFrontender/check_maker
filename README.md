# PDF Check Maker

Набор Python-инструментов для генерации PDF-документов (чеков, счетов, карточек) из HTML-шаблонов с помощью **WeasyPrint**.

## Структура проекта

```
pdf_check_maker/
├── run.py                  # кроссплатформенный лончер (venv + зависимости)
├── run.bat                 # запуск на Windows (двойной клик или cmd)
├── run.command             # запуск на macOS (двойной клик в Finder)
├── run.sh                  # запуск на macOS/Linux из терминала
├── requirements.txt        # зависимости
│
├── invoice_cli.py          # интерактивный генератор чеков (основной)
├── csv2pdf.py              # пакетная генерация PDF из CSV
├── html2pdf.py             # одиночная генерация PDF из HTML-шаблона
│
├── data/                   # CSV/JSON с данными для invoice_cli
│   ├── invoices.csv
│   └── invoices.json
├── templates/              # HTML-шаблоны для invoice_cli
│   ├── invoice_classic.html
│   └── invoice_modern.html
├── output/                 # сюда сохраняются PDF (создаётся автоматически)
│
├── example_template.html   # пример для html2pdf.py
├── example_data.json       # пример для html2pdf.py
├── template.html           # пример для csv2pdf.py
└── example.csv             # пример для csv2pdf.py
```

## Быстрый старт — один клик

Всё, что нужно сделать при первом запуске — **запустить лончер для вашей ОС**. Он автоматически создаст изолированное виртуальное окружение, поставит все зависимости и запустит приложение.

### Windows

Двойной клик по `run.bat` в проводнике **или** из `cmd`:

```cmd
run.bat
```

### macOS

Двойной клик по `run.command` в Finder (один раз может понадобиться дать разрешение в *Системных настройках → Безопасность*). Из терминала:

```bash
./run.command
# или
./run.sh
```

При первом запуске `run.*` сделает:

1. `python -m venv .venv` — создаст виртуальное окружение в папке `.venv/`.
2. `pip install -r requirements.txt` — поставит Python-зависимости в venv.
3. Сохранит SHA-256-хеш `requirements.txt` в `.venv/.deps-hash`, чтобы при повторных запусках не тратить время на `pip install`.
4. **Автоматически установит нативные зависимости WeasyPrint** под вашу ОС (через модуль `ensure_gtk.py`):
   - **Windows:** скачает официальный NSIS-установщик GTK3 Runtime с GitHub (`tschoonj/GTK-for-Windows-Runtime-Environment-Installer`) и поставит его в `%LOCALAPPDATA%\GTK3-Runtime-WeasyPrint` в тихом режиме (`/S /D=...`). Без прав администратора, однако Windows может показать UAC-запрос — просто подтвердите. После установки в `site-packages` venv'а пишется `sitecustomize.py`, который при каждом старте Python из этого venv вызывает `os.add_dll_directory()` для каталога `bin/` — так WeasyPrint гарантированно находит Pango/Cairo DLL, не требуя правки системного `PATH`.
   - **macOS:** выполнит `brew install pango` (если Homebrew установлен).
   - **Linux:** предложит установить пакеты системным менеджером (`apt install libpango-1.0-0 libpangoft2-1.0-0` и т.п.) — автоматически мы этого не делаем.
5. Перезапустит себя интерпретатором из `.venv` и запустит `invoice_cli.py`.

При последующих запусках этапы установки пропускаются — старт занимает доли секунды. Если `requirements.txt` изменился или GTK/pango пропали, компоненты автоматически переустановятся.

**Пропуск авто-установки GTK/pango.** Если вы уже установили их сами и не хотите, чтобы скрипт вмешивался:

```bash
# Windows (cmd)
set SKIP_NATIVE_DEPS=1 && run.bat

# Windows (PowerShell)
$env:SKIP_NATIVE_DEPS=1; .\run.bat

# macOS/Linux
SKIP_NATIVE_DEPS=1 ./run.command
```

### Без лончера

Если хотите собрать venv вручную:

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
python invoice_cli.py
```

## Системные зависимости WeasyPrint (делает `run.py` автоматически)

WeasyPrint требует нативных библиотек Pango, Cairo и GDK-PixBuf. Лончер `run.py` ставит их сам (см. выше). Если что-то пошло не так, вот ручная инструкция.

**Windows.** Установите [GTK for Windows Runtime Environment](https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases) (это именно то, что делает `ensure_gtk.py`).

**macOS.**

```bash
brew install pango
```

**Linux.**

```bash
sudo apt install libpango-1.0-0 libpangoft2-1.0-0
```

Без этих библиотек `pip install weasyprint` пройдёт, но PDF генерироваться не будет — появится ошибка загрузки cairo/pango в рантайме.

## Инструменты

### 1. `invoice_cli.py` — интерактивный генератор чеков

Сканирует `data/` и `templates/`, в меню даёт выбрать файл данных, шаблон и конкретный `invoice_id`, после чего создаёт PDF в `output/` и открывает его.

Запуск: `run.bat` (Windows) / `./run.command` (macOS) или `python invoice_cli.py`.

### 2. `csv2pdf.py` — пакетная генерация по CSV

```bash
python csv2pdf.py example.csv template.html --output-dir output
```

Для каждой строки CSV создаёт отдельный PDF. Опции: `--delimiter`, `--encoding`, `--name-column`, `--keep-html`, `--open-mode {none,first,all}`.

### 3. `html2pdf.py` — одиночная генерация с Jinja2

```bash
python html2pdf.py example_template.html -d example_data.json -o invoice.pdf
```

Поддержка Jinja2, JSON/YAML данных, внешних CSS, метаданных PDF, пакетного объединения нескольких HTML.

## Кириллица

Все шаблоны подключают Roboto через Google Fonts с cyrillic-subset и содержат fallback-стек `Roboto → DejaVu Sans → Liberation Sans → Arial`. При отсутствии интернета сработают системные шрифты.

## Удаление venv

Если нужно «начать заново»:

```bash
# Windows
rmdir /s /q .venv

# macOS/Linux
rm -rf .venv
```

При следующем запуске `run.*` всё пересоздастся.
