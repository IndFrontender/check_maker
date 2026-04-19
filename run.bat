@echo off
REM ---------------------------------------------------------------------------
REM  Лончер для Windows.
REM  Запускает run.py, который сам создаст .venv, установит зависимости
REM  и перезапустит приложение из изолированного окружения.
REM ---------------------------------------------------------------------------

setlocal
cd /d "%~dp0"

REM Пробуем команды py -> python -> python3 в этом порядке
where py >nul 2>&1
if %ERRORLEVEL%==0 (
    py -3 run.py %*
    goto :end
)

where python >nul 2>&1
if %ERRORLEVEL%==0 (
    python run.py %*
    goto :end
)

where python3 >nul 2>&1
if %ERRORLEVEL%==0 (
    python3 run.py %*
    goto :end
)

echo [ОШИБКА] Python не найден в PATH.
echo Установите Python с https://www.python.org/downloads/ и перезапустите.
pause
exit /b 1

:end
endlocal
