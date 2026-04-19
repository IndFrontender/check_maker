#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ensure_gtk — автоматическая установка нативных зависимостей WeasyPrint.

WeasyPrint написан на Python, но под капотом вызывает нативные библиотеки
Pango / Cairo / GDK-PixBuf (через cffi/ctypes). В Windows их нет «из коробки»,
в macOS нужно ставить из Homebrew. В Linux обычно ставятся системным
пакетным менеджером.

Модуль:
  * Определяет текущую ОС.
  * Проверяет, доступны ли уже нужные библиотеки.
  * Если нет — пытается установить их автоматически:
      Windows → скачивает официальный NSIS-установщик GTK3 Runtime
                из GitHub (tschoonj) и запускает его в тихом режиме (/S)
                с пользовательским каталогом установки (/D=%LOCALAPPDATA%\\...).
                Без прав администратора.
      macOS   → `brew install pango`.
      Linux   → ничего не делает (советуем apt/dnf/pacman).
  * Возвращает словарь с патчем окружения (PATH с GTK bin), который
    нужно передать подпроцессу, запускающему приложение.

Пропустить автоустановку: установить переменную окружения
    SKIP_NATIVE_DEPS=1
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


GTK_RELEASES_API = (
    "https://api.github.com/repos/tschoonj/"
    "GTK-for-Windows-Runtime-Environment-Installer/releases/latest"
)
# Запасной URL — если GitHub API недоступен. Обновить при необходимости.
GTK_FALLBACK_URL = (
    "https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/"
    "releases/download/2022-01-04/gtk3-runtime-3.24.31-2022-01-04-ts-win64.exe"
)

IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"


def _log(msg: str) -> None:
    print(f"[native-deps] {msg}")


# ============================ WINDOWS: GTK ====================================

def _windows_install_dir() -> Path:
    """Пользовательская директория для GTK — без прав администратора."""
    localapp = os.environ.get("LOCALAPPDATA", "")
    base = Path(localapp) if localapp else Path.home()
    return base / "GTK3-Runtime-WeasyPrint"


def _windows_find_gtk_bin() -> Path | None:
    """Ищет `...\\bin` с libpango*.dll в известных местах."""
    programfiles = os.environ.get("ProgramFiles", r"C:\Program Files")
    programfiles_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    candidates = [
        _windows_install_dir() / "bin",
        Path(programfiles) / "GTK3-Runtime Win64" / "bin",
        Path(programfiles_x86) / "GTK3-Runtime Win64" / "bin",
        # Альтернативные имена каталога (часть инсталляторов ставит без «3»):
        Path(programfiles) / "Gtk-Runtime" / "bin",
        Path(programfiles_x86) / "Gtk-Runtime" / "bin",
        Path(r"C:\GTK\bin"),
        Path(r"C:\gtk\bin"),
    ]
    # Плюс из PATH (если пользователь установил сам)
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry:
            candidates.append(Path(entry))

    seen: set[Path] = set()
    for p in candidates:
        try:
            rp = p.resolve()
        except OSError:
            continue
        if rp in seen or not rp.exists():
            continue
        seen.add(rp)
        if any(rp.glob("libpango-1.0-0.dll")) or any(rp.glob("libpango*.dll")):
            return rp
    return None


def _windows_download_installer(dest: Path) -> None:
    """Качает NSIS-установщик GTK3 Runtime. Пытается взять последний релиз."""
    dest.parent.mkdir(parents=True, exist_ok=True)

    url = GTK_FALLBACK_URL
    try:
        _log("Запрашиваю последний релиз GTK3 Runtime…")
        req = urllib.request.Request(
            GTK_RELEASES_API,
            headers={"User-Agent": "pdf-check-maker/1.0"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.load(resp)
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            if name.endswith("win64.exe"):
                url = asset["browser_download_url"]
                break
    except Exception as exc:
        _log(f"  Не удалось получить список релизов ({exc}). Использую fallback URL.")

    _log(f"Скачиваю установщик: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "pdf-check-maker/1.0"})
    with urllib.request.urlopen(req, timeout=300) as resp, dest.open("wb") as out:
        shutil.copyfileobj(resp, out)
    size_mb = dest.stat().st_size / 1e6
    _log(f"  Скачано: {dest} ({size_mb:.1f} MB)")


def _windows_install_gtk() -> Path:
    """Устанавливает GTK3 Runtime в пользовательский каталог и возвращает путь к bin."""
    existing = _windows_find_gtk_bin()
    if existing:
        _log(f"GTK уже доступен: {existing}")
        return existing

    target = _windows_install_dir()
    installer = target.parent / "gtk3-runtime-setup.exe"

    _windows_download_installer(installer)

    _log(f"Устанавливаю GTK3 Runtime в {target} (silent режим)…")
    _log("  Windows может показать UAC-запрос — подтвердите установку.")
    # NSIS: /S = silent, /D= = install dir.
    # ВАЖНО: /D= должен быть ПОСЛЕДНИМ параметром и без кавычек вокруг значения.
    # Используем shell=True, чтобы shell собрал строку корректно.
    cmd = f'"{installer}" /S /D={target}'
    result = subprocess.run(cmd, shell=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Установщик GTK завершился с кодом {result.returncode}. "
            "Попробуйте запустить его вручную или установить переменную "
            "SKIP_NATIVE_DEPS=1 и поставить GTK3 Runtime самостоятельно."
        )

    # Убираем временный installer
    try:
        installer.unlink()
    except OSError:
        pass

    bin_dir = _windows_find_gtk_bin()
    if not bin_dir:
        raise RuntimeError(f"GTK не обнаружен после установки в {target}.")
    _log(f"Готово: {bin_dir}")
    return bin_dir


# ============================= MACOS: pango ===================================

def _macos_find_pango() -> Path | None:
    """Ищет libpango в стандартных Homebrew / MacPorts префиксах."""
    for prefix in ("/opt/homebrew", "/usr/local", "/opt/local"):
        lib = Path(prefix) / "lib"
        if lib.exists() and list(lib.glob("libpango-1.0*.dylib")):
            return Path(prefix)
    return None


def _macos_install_pango() -> None:
    if _macos_find_pango():
        _log("pango уже установлен (Homebrew/MacPorts).")
        return

    brew = shutil.which("brew")
    if not brew:
        raise RuntimeError(
            "Homebrew не найден. Установите его командой:\n"
            '  /bin/bash -c "$(curl -fsSL '
            'https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"\n'
            "затем перезапустите скрипт."
        )

    _log("Запускаю `brew install pango` — это может занять несколько минут…")
    result = subprocess.run([brew, "install", "pango"])
    if result.returncode != 0:
        raise RuntimeError(f"brew install pango завершился с кодом {result.returncode}")
    _log("pango установлен.")


# ================================ ROUTER ======================================

def ensure() -> dict[str, str]:
    """
    Гарантирует, что нативные зависимости WeasyPrint доступны.

    Возвращает словарь env_patch с ключами:
      * "GTK_BIN_DIR" (Windows) — путь к каталогу ...\\bin с DLL.
    В run.py эти ключи используются для настройки окружения подпроцесса.
    """
    env_patch: dict[str, str] = {}

    if os.environ.get("SKIP_NATIVE_DEPS") == "1":
        _log("SKIP_NATIVE_DEPS=1 — пропускаю авто-установку GTK/pango.")
        if IS_WINDOWS:
            existing = _windows_find_gtk_bin()
            if existing:
                env_patch["GTK_BIN_DIR"] = str(existing)
        return env_patch

    if IS_WINDOWS:
        bin_dir = _windows_install_gtk()
        env_patch["GTK_BIN_DIR"] = str(bin_dir)
    elif IS_MACOS:
        _macos_install_pango()
    else:
        _log("Linux/другая ОС: нативные зависимости обычно ставятся системным "
             "пакетным менеджером. Например: sudo apt install libpango-1.0-0 "
             "libpangoft2-1.0-0")

    return env_patch


if __name__ == "__main__":
    try:
        patch = ensure()
        if patch:
            _log(f"Патч окружения: {patch}")
        sys.exit(0)
    except Exception as exc:
        _log(f"Ошибка: {exc}")
        sys.exit(1)
