#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Универсальный лончер для macOS / Linux из терминала.
# Для двойного клика в Finder на macOS используйте run.command.
# -----------------------------------------------------------------------------

set -e
cd "$(dirname "$0")"

PY=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PY="$candidate"
        break
    fi
done

if [ -z "$PY" ]; then
    echo "[ERROR] Python не найден в PATH."
    exit 1
fi

exec "$PY" run.py "$@"
