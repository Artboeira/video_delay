#!/usr/bin/env bash
# install.command — Bootstrap do Video Delay System no macOS.
# Duplo-clique no Finder. Valida Python 3 e baixa FFmpeg + MPV para vendor/.
# Idempotente: pode ser rodado quantas vezes for necessario.

set -u
cd "$(dirname "$0")"

printf "\n"
printf "  VIDEO DELAY SYSTEM  -  instalacao (macOS)\n"
printf "  =========================================\n\n"

if ! command -v python3 >/dev/null 2>&1; then
    printf "  [ERRO] Python 3 nao encontrado.\n\n"
    printf "  Opcoes de instalacao:\n"
    printf "    1) Baixar de https://www.python.org/downloads/macos/\n"
    printf "    2) Via Homebrew:  brew install python@3.11\n\n"
    printf "  Apos instalar, abra este arquivo (install.command) novamente.\n\n"
    read -r -p "  Pressione Enter para fechar." _
    exit 1
fi

printf "  Python: "
python3 --version
printf "\n"

printf "  Baixando FFmpeg e MPV para vendor/ (cerca de 150 MB).\n"
printf "  Esta etapa so precisa ser feita uma vez.\n\n"

python3 scripts/fetch_binaries.py
status=$?

printf "\n"
if [ "$status" -ne 0 ]; then
    printf "  [ERRO] Download dos binarios falhou. Veja as mensagens acima.\n"
    printf "  Consulte INSTALL.md, secao 'Solucao de problemas'.\n\n"
    read -r -p "  Pressione Enter para fechar." _
    exit "$status"
fi

printf "  Instalacao concluida.\n"
printf "  Para iniciar o sistema: duplo-clique em run.command.\n\n"
read -r -p "  Pressione Enter para fechar." _
