#!/usr/bin/env bash
# run-test.command — Inicia o Video Delay System em modo de teste no macOS.
# Usa fonte sintetica lavfi testsrc2 ao inves da placa de captura. Util para
# validar a instalacao sem hardware conectado.

set -u
cd "$(dirname "$0")"
exec "$(dirname "$0")/run.command" --test
