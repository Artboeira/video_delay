@echo off
REM Roda o sistema em modo de teste: captura sintetica via FFmpeg lavfi
REM (testsrc2) ao inves da placa de captura. Util para validar mudancas
REM sem precisar de hardware ou cabo HDMI conectado.
python main.py --test
