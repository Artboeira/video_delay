@echo off
REM run-test.bat - Inicia o Video Delay System em modo de teste no Windows.
REM Usa fonte sintetica lavfi testsrc2 ao inves da placa de captura. Util para
REM validar a instalacao sem hardware conectado.

cd /d "%~dp0"
call "%~dp0run.bat" --test
