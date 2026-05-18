@echo off
REM Executa toda a suite de testes do Video Delay System.
REM Os testes de integracao que precisam de FFmpeg sao pulados se o binario
REM nao estiver no PATH.
python -m unittest discover -s tests -p "test_*.py" -v
pause
