#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
invoice_cli — интерактивный генератор PDF-чеков.

Алгоритм:
  1. Сканирует ./data на наличие *.csv и *.json.
     CSV читается модулем csv (стандартная библиотека),
     JSON — модулем json.
  2. Сканирует ./templates на наличие *.html.
  3. Показывает пронумерованные меню выбора файла данных и шаблона.
  4. Выводит список invoice_id внутри выбранного файла.
  5. По выбранному invoice_id рендерит PDF через WeasyPrint и сохраняет в ./output.
  6. Автоматически открывает PDF в системном просмотрщике
     (os.startfile на Windows, `open` на macOS, `xdg-open` на Linux).

Кириллица корректно отображается благодаря Roboto (с cyrillic-subset)
и fallback на DejaVu Sans / Liberation Sans в HTML-шаблонах.
"""

from __future__ import annotations

import csv
import json
import os
import platform
import subprocess
import sys
import webbrowser
from html import escape
from pathlib import Path
from string import Template
from typing import Any

# ВАЖНО: импорт _gtk_preload должен произойти ДО weasyprint — он регистрирует
# каталог GTK bin в списке путей поиска DLL для Windows (см. _gtk_preload.py).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _gtk_preload  # noqa: F401  (side-effect import — регистрирует DLL-каталог)

# -------------------------------- НАСТРОЙКИ -----------------------------------

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
TEMPLATES_DIR = BASE_DIR / "templates"
OUTPUT_DIR = BASE_DIR / "output"

# Возможные имена поля с номером чека — проверяются в таком порядке
INVOICE_ID_KEYS = ("invoice_id", "invoice", "id", "number", "inv_id", "invoiceNumber")


# --------------------------- КОНСОЛЬНОЕ ОФОРМЛЕНИЕ ----------------------------

def _supports_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("TERM", "") != "dumb"


def c(text: str, code: str) -> str:
    """ANSI-цвет, если терминал поддерживает."""
    if not _supports_color():
        return text
    return f"\033[{code}m{text}\033[0m"


def header(title: str) -> None:
    line = "═" * max(60, len(title) + 4)
    print()
    print(c(line, "36"))
    print(c(f"  {title}", "1;36"))
    print(c(line, "36"))


def section(title: str) -> None:
    print()
    print(c(f"▸ {title}", "1;33"))


def print_menu(items: list[str]) -> None:
    width = len(str(len(items)))
    for idx, label in enumerate(items, 1):
        print(f"  {c(f'[{idx:>{width}}]', '32')} {label}")


def ask_choice(prompt: str, count: int) -> int:
    """Запрашивает у пользователя число 1..count и возвращает индекс (0-based)."""
    while True:
        try:
            raw = input(f"\n{prompt} (1-{count}, q — выход): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nПрервано пользователем.")
            sys.exit(130)
        if raw.lower() in {"q", "quit", "exit"}:
            print("Выход.")
            sys.exit(0)
        if not raw.isdigit():
            print(c("  Введите число.", "31"))
            continue
        n = int(raw)
        if not (1 <= n <= count):
            print(c(f"  Номер должен быть от 1 до {count}.", "31"))
            continue
        return n - 1


# ----------------------------- ЗАГРУЗКА ДАННЫХ --------------------------------

def load_csv(path: Path) -> list[dict[str, Any]]:
    """Читает CSV стандартной библиотекой csv. utf-8-sig корректно обрабатывает BOM."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def load_json(path: Path) -> list[dict[str, Any]]:
    """Читает JSON и возвращает список записей.

    Поддерживаемые форматы:
      - [ {...}, {...} ]
      - { "invoices": [ {...}, ... ] }
      - { "items":    [ {...}, ... ] }
      - одиночный объект { ... } — трактуется как один чек.
    """
    with path.open(encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("invoices", "records", "items", "data"):
            if isinstance(data.get(key), list):
                return data[key]
        # одиночный объект-чек
        return [data]
    raise ValueError(f"Неподдерживаемая структура JSON в {path}")


def load_data(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return load_csv(path)
    if suffix == ".json":
        return load_json(path)
    raise ValueError(f"Неизвестное расширение: {suffix}")


def detect_invoice_id(record: dict[str, Any]) -> str | None:
    """Находит значение поля, похожего на invoice_id."""
    for key in INVOICE_ID_KEYS:
        if key in record and record[key] not in (None, ""):
            return str(record[key])
    # регистронезависимый поиск
    lowered = {k.lower(): k for k in record.keys()}
    for key in INVOICE_ID_KEYS:
        if key.lower() in lowered:
            real_key = lowered[key.lower()]
            val = record[real_key]
            if val not in (None, ""):
                return str(val)
    return None


def short_repr(record: dict[str, Any]) -> str:
    """Краткое описание чека для меню."""
    for key in ("client", "customer", "client_name", "name", "title"):
        if record.get(key):
            return str(record[key])
    return ""


# --------------------------- РЕНДЕРИНГ ШАБЛОНА --------------------------------

def render_template(template_path: Path, record: dict[str, Any]) -> str:
    """
    Подставляет плоские поля record в HTML через string.Template.
    Дополнительно формирует $items_html из record['items'] (если есть)
    и $total_formatted (если есть).
    """
    tpl_text = template_path.read_text(encoding="utf-8")
    tpl = Template(tpl_text)

    # Плоские поля
    flat = {k: str(v) for k, v in record.items() if not isinstance(v, (list, dict))}

    # Таблица позиций, если есть
    items_html = ""
    total = 0.0
    if isinstance(record.get("items"), list) and record["items"]:
        rows = []
        for i, it in enumerate(record["items"], 1):
            name = escape(str(it.get("name", "")))
            qty = float(it.get("qty", it.get("quantity", 0)) or 0)
            price = float(it.get("price", 0) or 0)
            line_total = qty * price
            total += line_total
            rows.append(
                f"<tr>"
                f"<td>{i}</td>"
                f"<td>{name}</td>"
                f"<td>{qty:g}</td>"
                f"<td>{price:,.2f}</td>"
                f"<td>{line_total:,.2f}</td>"
                f"</tr>"
            )
        items_html = "\n".join(rows).replace(",", " ")  # узкий неразрывный формат тысяч

    # Экранируем все плоские строки
    safe = {k: escape(v) for k, v in flat.items()}
    safe["items_html"] = items_html  # уже экранирован
    safe["total_formatted"] = f"{total:,.2f}".replace(",", " ") if total else safe.get("total", "")

    return tpl.safe_substitute(safe)


# ---------------------------- ГЕНЕРАЦИЯ PDF -----------------------------------

def render_pdf(html_string: str, pdf_path: Path, base_url: Path) -> None:
    try:
        from weasyprint import HTML
    except ImportError:
        raise SystemExit(
            "Ошибка: WeasyPrint не установлен. Установите: pip install weasyprint"
        )
    except OSError as exc:
        raise SystemExit(
            "Ошибка загрузки нативных библиотек WeasyPrint (GTK/Pango/Cairo):\n"
            f"    {exc}\n\n"
            "Запустите приложение через run.bat / run.command — он сам установит\n"
            "GTK3 Runtime и пропишет DLL-каталог. Либо поставьте GTK вручную в\n"
            "  %LOCALAPPDATA%\\GTK3-Runtime-WeasyPrint\\bin\n"
            "или C:\\Program Files\\GTK3-Runtime Win64\\bin."
        )
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_string, base_url=str(base_url.resolve())).write_pdf(str(pdf_path))


def open_in_system(path: Path) -> None:
    abs_path = path.resolve()
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(str(abs_path))  # type: ignore[attr-defined]
            return
        if system == "Darwin":
            subprocess.run(["open", str(abs_path)], check=False)
            return
        subprocess.run(["xdg-open", str(abs_path)], check=False)
        return
    except Exception:
        pass
    try:
        webbrowser.open(abs_path.as_uri())
    except Exception as exc:
        print(c(f"  Не удалось открыть файл автоматически: {exc}", "31"), file=sys.stderr)


# ----------------------------- ОСНОВНОЙ ПОТОК ---------------------------------

def list_data_files() -> list[Path]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(
        [p for p in DATA_DIR.iterdir() if p.suffix.lower() in {".csv", ".json"}]
    )
    return files


def list_templates() -> list[Path]:
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    return sorted([p for p in TEMPLATES_DIR.iterdir() if p.suffix.lower() == ".html"])


def format_data_file(path: Path, count: int) -> str:
    return f"{path.name:<32} {c(f'({path.suffix[1:].upper()}, {count} зап.)', '90')}"


def main() -> int:
    header("Генератор PDF-чеков  ·  WeasyPrint")

    # --- 1. Файлы с данными ---
    data_files = list_data_files()
    if not data_files:
        print(c(f"\nВ папке {DATA_DIR} не найдено ни одного CSV/JSON.", "31"))
        return 1

    # Подсчитаем записи заранее, чтобы вывести красиво
    loaded: list[tuple[Path, list[dict[str, Any]]]] = []
    for p in data_files:
        try:
            loaded.append((p, load_data(p)))
        except Exception as exc:
            print(c(f"  Пропускаю {p.name}: {exc}", "31"))

    if not loaded:
        print(c("Не удалось загрузить ни одного файла.", "31"))
        return 1

    section("Доступные файлы с данными:")
    print_menu([format_data_file(p, len(recs)) for p, recs in loaded])
    di = ask_choice("Выберите файл данных", len(loaded))
    data_path, records = loaded[di]

    # --- 2. Шаблоны ---
    templates = list_templates()
    if not templates:
        print(c(f"\nВ папке {TEMPLATES_DIR} не найдено ни одного HTML-шаблона.", "31"))
        return 1

    section("Доступные шаблоны:")
    print_menu([p.name for p in templates])
    ti = ask_choice("Выберите шаблон", len(templates))
    template_path = templates[ti]

    # --- 3. Invoice ID ---
    invoice_ids: list[tuple[int, str, dict[str, Any]]] = []
    for idx, rec in enumerate(records):
        inv = detect_invoice_id(rec)
        if inv:
            invoice_ids.append((idx, inv, rec))

    if not invoice_ids:
        print(c("\nВ файле не найдено поле invoice_id / id / number.", "31"))
        print(c(f"Проверяемые ключи: {', '.join(INVOICE_ID_KEYS)}", "90"))
        return 1

    section(f"Доступные чеки в {data_path.name}:")
    menu_items = []
    for _, inv, rec in invoice_ids:
        extra = short_repr(rec)
        label = f"{c(inv, '1')}"
        if extra:
            label += f"  {c('—', '90')} {extra}"
        menu_items.append(label)
    print_menu(menu_items)
    ii = ask_choice("Выберите чек (invoice_id)", len(invoice_ids))
    _, invoice_id, record = invoice_ids[ii]

    # --- 4. Рендеринг ---
    html_string = render_template(template_path, record)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in invoice_id)
    pdf_path = OUTPUT_DIR / f"{safe_name}.pdf"

    section("Генерация PDF:")
    print(f"  Шаблон : {template_path.name}")
    print(f"  Чек    : {invoice_id}")
    print(f"  Цель   : {pdf_path}")

    render_pdf(html_string, pdf_path, base_url=template_path.parent)
    print(c(f"\n✓ PDF создан: {pdf_path.resolve()}", "1;32"))

    # --- 5. Открытие ---
    print("  Открываю в системном просмотрщике…")
    open_in_system(pdf_path)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nПрервано.")
        sys.exit(130)
