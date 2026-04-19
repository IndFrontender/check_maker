#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
_gtk_preload — регистрирует каталог GTK bin как источник DLL *до* того, как
WeasyPrint через cffi/ctypes попытается загрузить libgobject / libpango / ...

Зачем это нужно
---------------
Начиная с Python 3.8 Windows больше не ищет зависимые DLL по переменной PATH
(см. PEP 587 / LOAD_LIBRARY_SEARCH_DEFAULT_DIRS). Если пользователь установил
GTK3 Runtime (например, в C:\\Program Files\\Gtk-Runtime\\bin), то сама
`libgobject-2.0-0.dll` находится, но её соседи (libglib, libffi, libiconv,
libintl...) — нет. Результат — OSError 0x7e (ERROR_MOD_NOT_FOUND).

Решение — явный вызов `os.add_dll_directory()` с каталогом bin из GTK Runtime.
Лончер `run.py` делает это через сгенерированный sitecustomize.py в venv, но
если пользователь запускает CLI-скрипт напрямую системным Python, этот слой
отсутствует — тогда нас спасает данный модуль.

На macOS и Linux — no-op: там зависимости ищутся через системные механизмы
(Homebrew/MacPorts / ldconfig).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Файл-маркер, по наличию которого мы опознаём каталог GTK bin.
_GTK_MARKER = "libgobject-2.0-0.dll"


def _windows_candidates() -> list[Path]:
    """Собирает список правдоподобных каталогов GTK bin на Windows."""
    localapp = os.environ.get("LOCALAPPDATA", "")
    programfiles = os.environ.get("ProgramFiles", r"C:\Program Files")
    programfiles_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")

    candidates: list[Path] = []
    if localapp:
        candidates.append(Path(localapp) / "GTK3-Runtime-WeasyPrint" / "bin")
    candidates.extend(
        [
            Path(programfiles) / "GTK3-Runtime Win64" / "bin",
            Path(programfiles_x86) / "GTK3-Runtime Win64" / "bin",
            # Путь, которым пользуется NSIS-установщик в ряде сборок:
            Path(programfiles) / "Gtk-Runtime" / "bin",
            Path(programfiles_x86) / "Gtk-Runtime" / "bin",
            Path(r"C:\GTK\bin"),
            Path(r"C:\gtk\bin"),
        ]
    )

    # Дополнительно — всё, что пользователь уже прописал в PATH.
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry:
            candidates.append(Path(entry))

    return candidates


def _find_gtk_bin() -> Path | None:
    seen: set[str] = set()
    for cand in _windows_candidates():
        try:
            resolved = cand.resolve()
        except OSError:
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        if not resolved.exists() or not resolved.is_dir():
            continue
        if (resolved / _GTK_MARKER).exists():
            return resolved
    return None


def preload() -> Path | None:
    """
    Регистрирует каталог GTK bin для поиска DLL.

    Возвращает путь, который был подключён, либо None, если каталог не найден
    или платформа не Windows.
    """
    if sys.platform != "win32":
        return None

    gtk_bin = _find_gtk_bin()
    if gtk_bin is None:
        return None

    # Python 3.8+: явная регистрация каталога DLL.
    add_dll_dir = getattr(os, "add_dll_directory", None)
    if add_dll_dir is not None:
        try:
            add_dll_dir(str(gtk_bin))
        except (OSError, FileNotFoundError):
            pass

    # Дополнительно подкидываем в PATH — на случай библиотек, которые
    # полагаются на старое поведение или запускают дочерние процессы.
    gtk_str = str(gtk_bin)
    current_path = os.environ.get("PATH", "")
    if gtk_str.lower() not in current_path.lower():
        os.environ["PATH"] = gtk_str + os.pathsep + current_path

    return gtk_bin


# Автоматическая активация при импорте — это главный сценарий использования.
PRELOADED_GTK_BIN = preload()


if __name__ == "__main__":
    if sys.platform != "win32":
        print("[gtk-preload] не-Windows платформа — ничего делать не нужно.")
        sys.exit(0)
    if PRELOADED_GTK_BIN:
        print(f"[gtk-preload] подключён каталог GTK: {PRELOADED_GTK_BIN}")
        sys.exit(0)
    print(
        "[gtk-preload] GTK Runtime не найден. Установите его через run.py / run.bat "
        "или вручную (https://github.com/tschoonj/"
        "GTK-for-Windows-Runtime-Environment-Installer/releases).",
        file=sys.stderr,
    )
    sys.exit(1)
