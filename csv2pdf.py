#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
csv2pdf — CLI-скрипт: CSV → HTML → PDF.

Что делает:
  1. Читает CSV (стандартная библиотека — модуль csv).
  2. Загружает HTML-шаблон с плейсхолдерами вида $name или ${name}
     (стандартная библиотека — string.Template).
  3. Для каждой строки CSV подставляет данные в шаблон.
  4. Сохраняет готовый HTML рядом с PDF в папке output/.
  5. Конвертирует HTML в PDF через WeasyPrint.
  6. Автоматически открывает PDF в браузере / системном просмотрщике
     (работает на Windows и macOS).

Кириллица корректно отображается благодаря подключению Roboto (с cyrillic-subset)
и fallback-стеку Liberation Sans / DejaVu Sans / Arial.

Пример запуска:

    python csv2pdf.py example.csv template.html --output-dir output
    python csv2pdf.py data.csv tpl.html --open-mode all
    python csv2pdf.py data.csv tpl.html --no-open
"""

from __future__ import annotations

import argparse
import csv
import os
import platform
import re
import subprocess
import sys
import webbrowser
from html import escape
from pathlib import Path
from string import Template

# ВАЖНО: импорт _gtk_preload должен произойти ДО weasyprint — он регистрирует
# каталог GTK bin в списке путей поиска DLL для Windows (см. _gtk_preload.py).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _gtk_preload  # noqa: F401  (side-effect import — регистрирует DLL-каталог)


# ---------------------------- ВСПОМОГАТЕЛЬНЫЕ ---------------------------------

_FNAME_BAD = re.compile(r"[^\w.\-]+", flags=re.UNICODE)


def sanitize_filename(value: str, default: str = "record") -> str:
    """Превращает произвольную строку в безопасное имя файла."""
    cleaned = _FNAME_BAD.sub("_", value).strip("._")
    return cleaned or default


def load_template(path: Path) -> Template:
    """Читает HTML-шаблон и оборачивает его в string.Template."""
    return Template(path.read_text(encoding="utf-8"))


def render_row(template: Template, row: dict[str, str]) -> str:
    """
    Подставляет данные строки в шаблон.
    Значения экранируются через html.escape, чтобы спецсимволы не сломали HTML.
    safe_substitute не падает на отсутствующих плейсхолдерах.
    """
    safe_row = {key: escape(str(value or "")) for key, value in row.items()}
    return template.safe_substitute(safe_row)


def open_in_system(path: Path) -> None:
    """
    Открывает файл в браузере / системном приложении.
    Поддерживает Windows, macOS и Linux (fallback).
    """
    abs_path = path.resolve()
    system = platform.system()

    try:
        if system == "Windows":
            # Самый надёжный способ в Windows — os.startfile
            os.startfile(str(abs_path))  # type: ignore[attr-defined]
            return
        if system == "Darwin":
            subprocess.run(["open", str(abs_path)], check=False)
            return
        # Linux
        subprocess.run(["xdg-open", str(abs_path)], check=False)
        return
    except Exception:
        pass

    # Финальный фоллбэк — через webbrowser (большинство браузеров умеют PDF)
    try:
        webbrowser.open(abs_path.as_uri())
    except Exception as exc:
        print(f"Не удалось открыть {abs_path}: {exc}", file=sys.stderr)


def html_to_pdf(html_string: str, pdf_path: Path, base_url: Path) -> None:
    """Рендерит HTML-строку в PDF через WeasyPrint."""
    try:
        from weasyprint import HTML  # локальный импорт, чтобы --help работал и без weasyprint
    except ImportError:
        raise SystemExit(
            "Ошибка: библиотека WeasyPrint не установлена.\n"
            "Установите: pip install weasyprint"
        )
    except OSError as exc:
        raise SystemExit(
            "Ошибка загрузки нативных библиотек WeasyPrint (GTK/Pango/Cairo):\n"
            f"    {exc}\n\n"
            "Запустите через run.bat / run.command — он установит GTK и пропишет "
            "DLL-каталог автоматически. Либо установите GTK3 Runtime вручную в\n"
            "  %LOCALAPPDATA%\\GTK3-Runtime-WeasyPrint\\bin\n"
            "или C:\\Program Files\\GTK3-Runtime Win64\\bin."
        )

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_string, base_url=str(base_url.resolve())).write_pdf(
        target=str(pdf_path)
    )


# --------------------------------- CLI ----------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="csv2pdf",
        description="Генерирует отдельный PDF для каждой строки CSV по HTML-шаблону.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "csv_file",
        type=Path,
        help="Путь к CSV-файлу с данными.",
    )
    parser.add_argument(
        "template_file",
        type=Path,
        help="Путь к HTML-шаблону с плейсхолдерами $name или ${name}.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output"),
        help="Папка для сгенерированных HTML и PDF.",
    )
    parser.add_argument(
        "--delimiter",
        default=",",
        help="Разделитель колонок в CSV.",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8-sig",
        help="Кодировка CSV-файла (utf-8-sig корректно обрабатывает BOM).",
    )
    parser.add_argument(
        "--name-column",
        default=None,
        help="Колонка, значение которой использовать в имени PDF-файла. "
             "По умолчанию берётся первая колонка или порядковый номер.",
    )
    parser.add_argument(
        "--keep-html",
        action="store_true",
        help="Не удалять промежуточные HTML-файлы (по умолчанию они сохраняются).",
    )
    parser.add_argument(
        "--open-mode",
        choices=("none", "first", "all"),
        default="first",
        help="Что открывать после генерации: ничего, только первый PDF, или все.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Не открывать PDF после генерации (эквивалент --open-mode none).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Подробный вывод.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.csv_file.exists():
        print(f"CSV-файл не найден: {args.csv_file}", file=sys.stderr)
        return 2
    if not args.template_file.exists():
        print(f"Шаблон не найден: {args.template_file}", file=sys.stderr)
        return 2

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    template = load_template(args.template_file)

    # Читаем CSV и формируем PDF для каждой строки
    generated: list[Path] = []
    with args.csv_file.open(encoding=args.encoding, newline="") as f:
        reader = csv.DictReader(f, delimiter=args.delimiter)
        if reader.fieldnames is None:
            print("CSV пуст или не содержит заголовков.", file=sys.stderr)
            return 1

        name_col = args.name_column or reader.fieldnames[0]

        for idx, row in enumerate(reader, start=1):
            # Имя файла
            raw_name = row.get(name_col) or f"record_{idx:03d}"
            base_name = sanitize_filename(str(raw_name), default=f"record_{idx:03d}")

            html_path = output_dir / f"{base_name}.html"
            pdf_path = output_dir / f"{base_name}.pdf"

            if args.verbose:
                print(f"[{idx}] {base_name} — рендер HTML…")

            rendered = render_row(template, row)
            html_path.write_text(rendered, encoding="utf-8")

            if args.verbose:
                print(f"[{idx}] {base_name} — конвертация в PDF…")

            html_to_pdf(
                html_string=rendered,
                pdf_path=pdf_path,
                base_url=args.template_file.parent,
            )

            if not args.keep_html:
                try:
                    html_path.unlink()
                except OSError:
                    pass

            generated.append(pdf_path)
            print(f"✓ {pdf_path}")

    # Открытие PDF
    open_mode = "none" if args.no_open else args.open_mode
    if generated and open_mode != "none":
        targets = generated if open_mode == "all" else generated[:1]
        for path in targets:
            open_in_system(path)

    print(f"\nГотово. Сгенерировано файлов: {len(generated)}. Папка: {output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
