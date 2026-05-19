#!/usr/bin/env bash
# run.command — Inicia o Video Delay System no macOS.
# Duplo-clique no Finder. Abre o painel em http://127.0.0.1:8765/ no navegador.
# Pressione q no terminal (ou feche a janela) para encerrar.

set -u
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    printf "\n  [ERRO] Python 3 nao encontrado. Rode install.command primeiro.\n\n"
    read -r -p "  Pressione Enter para fechar." _
    exit 1
fi

if [ ! -d "vendor/mac-arm64" ] && [ ! -d "vendor/mac-x86_64" ]; then
    printf "\n  [ERRO] Pasta vendor/ vazia. Rode install.command primeiro\n"
    printf "         para baixar os binarios FFmpeg e MPV.\n\n"
    read -r -p "  Pressione Enter para fechar." _
    exit 1
fi

python3 main.py "$@"
status=$?

printf "\n"
read -r -p "  Sistema encerrado. Pressione Enter para fechar." _
exit "$status"
