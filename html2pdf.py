#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
html2pdf — CLI-инструмент для генерации PDF из HTML-шаблона
с использованием WeasyPrint и Jinja2.

Примеры использования:
    # Простая конвертация HTML в PDF
    python html2pdf.py invoice.html -o invoice.pdf

    # С подстановкой данных из JSON через Jinja2
    python html2pdf.py template.html -d data.json -o result.pdf

    # С внешним CSS, метаданными и авто-открытием файла
    python html2pdf.py report.html -d data.yaml --css styles.css \
        --title "Отчёт за апрель" --author "Igor" --open

    # Пакетная обработка нескольких файлов
    python html2pdf.py page1.html page2.html page3.html -o combined.pdf
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any

# ВАЖНО: этот импорт должен быть ДО weasyprint — он регистрирует каталог
# GTK bin в списке путей поиска DLL для Windows (см. _gtk_preload.py).
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _gtk_preload  # noqa: F401  (side-effect import — регистрирует DLL-каталог)

import click

try:
    from weasyprint import CSS, HTML
except ImportError:
    click.echo(
        "Ошибка: библиотека WeasyPrint не установлена.\n"
        "Установите её командой: pip install weasyprint",
        err=True,
    )
    sys.exit(1)
except OSError as _gtk_error:
    click.echo(
        "Ошибка загрузки нативных библиотек WeasyPrint (GTK/Pango/Cairo):\n"
        f"    {_gtk_error}\n\n"
        "Скорее всего, не установлен GTK3 Runtime либо Python не знает, где его искать.\n"
        "Решения:\n"
        "  1. Запустите приложение через лончер: run.bat (Windows) / ./run.command (macOS).\n"
        "     Он установит GTK автоматически и пропишет DLL-каталог.\n"
        "  2. Либо установите GTK3 Runtime вручную и убедитесь, что он лежит в\n"
        "     %LOCALAPPDATA%\\GTK3-Runtime-WeasyPrint\\bin или\n"
        "     C:\\Program Files\\GTK3-Runtime Win64\\bin.\n"
        "  3. Если GTK установлен в нестандартный путь, добавьте его каталог `bin`\n"
        "     в список _windows_candidates() файла _gtk_preload.py.",
        err=True,
    )
    sys.exit(1)

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    JINJA_AVAILABLE = True
except ImportError:
    JINJA_AVAILABLE = False


# ----------------------------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ------------------------

def load_data(data_path: Path) -> dict[str, Any]:
    """Загружает данные из JSON или YAML файла для подстановки в шаблон."""
    suffix = data_path.suffix.lower()
    text = data_path.read_text(encoding="utf-8")

    if suffix in {".json"}:
        return json.loads(text)
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError:
            raise click.ClickException(
                "Для YAML-файлов нужен PyYAML. Установите: pip install pyyaml"
            )
        return yaml.safe_load(text)

    raise click.ClickException(
        f"Неподдерживаемый формат данных: {suffix}. Используйте .json, .yaml или .yml"
    )


def render_template(html_path: Path, data: dict[str, Any]) -> str:
    """Рендерит Jinja2-шаблон с подставленными данными."""
    if not JINJA_AVAILABLE:
        raise click.ClickException(
            "Для работы с шаблонами нужен Jinja2. Установите: pip install jinja2"
        )

    env = Environment(
        loader=FileSystemLoader(str(html_path.parent)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(html_path.name)
    return template.render(**data)


def open_file_in_system(path: Path) -> None:
    """Открывает PDF-файл в браузере / системном приложении по умолчанию."""
    abs_path = path.resolve()
    try:
        # Сначала пробуем открыть через webbrowser (в большинстве систем
        # это откроет PDF в браузере, если он назначен по умолчанию).
        opened = webbrowser.open(abs_path.as_uri())
        if opened:
            return
    except Exception:
        pass

    # Фоллбэк: платформенно-специфичное открытие
    system = platform.system()
    try:
        if system == "Windows":
            os.startfile(str(abs_path))  # type: ignore[attr-defined]
        elif system == "Darwin":
            subprocess.run(["open", str(abs_path)], check=False)
        else:  # Linux и прочие
            subprocess.run(["xdg-open", str(abs_path)], check=False)
    except Exception as exc:
        click.echo(f"Не удалось открыть файл автоматически: {exc}", err=True)


def build_pdf(
    html_sources: list[tuple[str, Path]],
    output_path: Path,
    css_files: list[Path],
    base_url: Path | None,
    metadata: dict[str, str],
) -> None:
    """
    Рендерит список HTML-строк в единый PDF.

    html_sources: список кортежей (html_string, base_path_for_resources).
    """
    documents = []
    stylesheets = [CSS(filename=str(p)) for p in css_files]

    for html_string, base_path in html_sources:
        resolved_base = str((base_url or base_path).resolve())
        html = HTML(string=html_string, base_url=resolved_base)
        documents.append(html.render(stylesheets=stylesheets))

    if not documents:
        raise click.ClickException("Нет HTML-источников для рендеринга.")

    # Объединяем страницы всех документов в один PDF
    first, *rest = documents
    all_pages = list(first.pages)
    for doc in rest:
        all_pages.extend(doc.pages)

    final_doc = first.copy(all_pages)

    # Применяем метаданные PDF, если указаны
    if metadata:
        md = final_doc.metadata
        if metadata.get("title"):
            md.title = metadata["title"]
        if metadata.get("author"):
            md.authors = [metadata["author"]]
        if metadata.get("subject"):
            md.description = metadata["subject"]
        if metadata.get("keywords"):
            md.keywords = [
                k.strip() for k in metadata["keywords"].split(",") if k.strip()
            ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    final_doc.write_pdf(target=str(output_path))


# ----------------------------------- CLI -------------------------------------

@click.command(
    context_settings={"help_option_names": ["-h", "--help"]},
    help="Генерация PDF из HTML-шаблона с помощью WeasyPrint.",
)
@click.argument(
    "html_files",
    nargs=-1,
    required=True,
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
)
@click.option(
    "-o", "--output",
    "output",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    default=None,
    help="Путь к выходному PDF-файлу. По умолчанию — имя первого HTML с расширением .pdf",
)
@click.option(
    "-d", "--data",
    "data_file",
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    default=None,
    help="JSON или YAML файл с данными для подстановки в Jinja2-шаблон.",
)
@click.option(
    "--css",
    "css_files",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, readable=True, path_type=Path),
    help="Дополнительный CSS-файл. Можно указать несколько раз.",
)
@click.option(
    "--base-url",
    "base_url",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Базовая директория для разрешения относительных путей (картинки, шрифты, CSS).",
)
@click.option("--title", default=None, help="Заголовок PDF (метаданные).")
@click.option("--author", default=None, help="Автор PDF (метаданные).")
@click.option("--subject", default=None, help="Тема/описание PDF (метаданные).")
@click.option("--keywords", default=None, help="Ключевые слова через запятую.")
@click.option(
    "--no-template", is_flag=True, default=False,
    help="Пропустить обработку Jinja2 — использовать HTML как есть.",
)
@click.option(
    "--open/--no-open",
    "auto_open",
    default=True,
    show_default=True,
    help="Открыть сгенерированный PDF в браузере/системе после создания.",
)
@click.option("-v", "--verbose", is_flag=True, help="Подробный вывод.")
def main(
    html_files: tuple[Path, ...],
    output: Path | None,
    data_file: Path | None,
    css_files: tuple[Path, ...],
    base_url: Path | None,
    title: str | None,
    author: str | None,
    subject: str | None,
    keywords: str | None,
    no_template: bool,
    auto_open: bool,
    verbose: bool,
) -> None:
    """Генерация PDF из HTML-шаблона(ов)."""

    # 1. Определяем путь к результату
    if output is None:
        output = html_files[0].with_suffix(".pdf")

    # 2. Загружаем данные для Jinja2, если указаны
    data: dict[str, Any] = {}
    if data_file is not None:
        if verbose:
            click.echo(f"Читаю данные из {data_file}…")
        data = load_data(data_file) or {}

    # 3. Рендерим каждый HTML-файл
    html_sources: list[tuple[str, Path]] = []
    for html_path in html_files:
        if verbose:
            click.echo(f"Обрабатываю {html_path}…")

        if no_template or (not data and not JINJA_AVAILABLE):
            html_string = html_path.read_text(encoding="utf-8")
        else:
            # Даже без data имеет смысл прогнать через Jinja2 —
            # чтобы работали include/extends/for и пр.
            try:
                html_string = render_template(html_path, data)
            except click.ClickException:
                # Jinja2 не установлен — используем raw HTML
                html_string = html_path.read_text(encoding="utf-8")

        html_sources.append((html_string, html_path.parent))

    # 4. Собираем метаданные
    metadata = {
        "title": title,
        "author": author,
        "subject": subject,
        "keywords": keywords,
    }
    metadata = {k: v for k, v in metadata.items() if v}

    # 5. Генерируем PDF
    if verbose:
        click.echo(f"Генерирую PDF → {output}")
    build_pdf(
        html_sources=html_sources,
        output_path=output,
        css_files=list(css_files),
        base_url=base_url,
        metadata=metadata,
    )

    click.secho(f"✓ PDF создан: {output.resolve()}", fg="green")

    # 6. Авто-открытие
    if auto_open:
        if verbose:
            click.echo("Открываю PDF…")
        open_file_in_system(output)


if __name__ == "__main__":
    main()
