#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Лончер для macOS (двойной клик в Finder открывает его в Terminal).
# Запускает run.py, который сам создаст .venv, установит зависимости
# и перезапустит приложение из изолированного окружения.
# -----------------------------------------------------------------------------

set -e

# Переходим в директорию скрипта
cd "$(dirname "$0")"

# Ищем подходящий Python
PY=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PY="$candidate"
        break
    fi
done

if [ -z "$PY" ]; then
    echo "[ОШИБКА] Python не найден."
    echo "Установите Python: brew install python  (или https://www.python.org/downloads/)"
    read -r -p "Нажмите Enter для выхода…" _
    exit 1
fi

"$PY" run.py "$@"
