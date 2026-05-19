@echo off
REM install.bat - Bootstrap do Video Delay System no Windows.
REM Duplo-clique no Explorer. Valida Python 3 e baixa FFmpeg + MPV para vendor\.
REM Idempotente: pode ser rodado quantas vezes for necessario.

title Video Delay System - Instalacao
cd /d "%~dp0"

echo.
echo   VIDEO DELAY SYSTEM  -  instalacao (Windows)
echo   ===========================================
echo.

call :find_python
if errorlevel 1 (
    echo   [ERRO] Python 3 nao encontrado.
    echo.
    echo   Baixe e instale de: https://www.python.org/downloads/windows/
    echo   IMPORTANTE: marque "Add Python to PATH" durante a instalacao.
    echo.
    echo   Apos instalar, execute este arquivo ^(install.bat^) novamente.
    echo.
    pause
    exit /b 1
)

echo   Python:
%PY_CMD% --version
echo.

echo   Baixando FFmpeg e MPV para vendor\ ^(cerca de 150 MB^).
echo   Esta etapa so precisa ser feita uma vez.
echo.

%PY_CMD% scripts\fetch_binaries.py
if errorlevel 1 (
    echo.
    echo   [ERRO] Download dos binarios falhou. Veja as mensagens acima.
    echo   Consulte INSTALL.md, secao "Solucao de problemas".
    echo.
    pause
    exit /b 1
)

echo.
echo   Instalacao concluida.
echo   Para iniciar o sistema: duplo-clique em run.bat.
echo.
pause
exit /b 0

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
