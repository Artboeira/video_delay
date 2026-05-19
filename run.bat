@echo off
REM run.bat - Inicia o Video Delay System no Windows.
REM Duplo-clique no Explorer. Abre o painel em http://127.0.0.1:8765/ no navegador.
REM Pressione q na janela (ou feche-a) para encerrar.

title Video Delay System - Estudio AB
cd /d "%~dp0"

call :find_python
if errorlevel 1 (
    echo.
    echo   [ERRO] Python 3 nao encontrado. Rode install.bat primeiro.
    echo.
    pause
    exit /b 1
)

if not exist "vendor\win-x64" (
    echo.
    echo   [ERRO] Pasta vendor\win-x64 nao encontrada.
    echo          Rode install.bat primeiro para baixar FFmpeg e MPV.
    echo.
    pause
    exit /b 1
)

%PY_CMD% main.py %*
set "exit_code=%errorlevel%"

echo.
echo   Sistema encerrado.
pause
exit /b %exit_code%

:find_python
where py >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=py -3"
    exit /b 0
)
where python >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=python"
    exit /b 0
)
exit /b 1
