@echo off
title Video Delay System — Estudio AB
cd /d "%~dp0"

echo.
echo  Verificando dependencias...
echo.

where ffmpeg >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERRO] FFmpeg nao encontrado no PATH.
    echo         Baixe em: https://ffmpeg.org/download.html
    echo         E adicione a pasta bin ao PATH do sistema.
    pause
    exit /b 1
)

where mpv >nul 2>&1
if %errorlevel% neq 0 (
    echo  [ERRO] MPV nao encontrado no PATH.
    echo         Baixe em: https://mpv.io/installation/
    echo         E adicione ao PATH do sistema.
    pause
    exit /b 1
)

echo  FFmpeg: OK
echo  MPV:    OK
echo.

python main.py
pause
