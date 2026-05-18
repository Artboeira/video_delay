"""
modules/logging_setup.py — Setup de logging persistente e null-safe.

O app empacotado com PyInstaller `--windowed` no Mac tem `sys.stdout = None` e
`sys.stderr = None`. Qualquer `print()` residual no código (próprio ou de libs)
levanta AttributeError silencioso e quebra o boot.

Este módulo:
  1. Substitui stdout/stderr por arquivos no-op quando ausentes (defesa universal).
  2. Configura um `RotatingFileHandler` em `paths.log_path()` para que toda a
     atividade do app fique gravada e possa ser auditada pelo cliente (e mandada
     por email se algo der errado).
  3. Adiciona um `StreamHandler` no console **somente** se houver TTY — em modo
     frozen o console nunca aparece, então essa branch é morta lá.

Uso:
    from modules.logging_setup import setup_logging, log
    setup_logging()
    log.info("ola")
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from .paths import ensure_user_data_dir, log_path, is_frozen


# Logger principal usado pelo app inteiro. Importável como
# `from modules.logging_setup import log`.
log = logging.getLogger("videodelay")


_FORMAT = "%(asctime)s %(levelname)-5s %(name)s :: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


class _DevNull:
    """Sink no-op para substituir sys.stdout/stderr quando são None."""
    def write(self, *_args, **_kw): return 0
    def flush(self): return None
    def isatty(self): return False
    def fileno(self): raise OSError("no fileno")


def _neutralize_streams():
    """
    Defende contra `print()` quando empacotado: troca None por _DevNull.
    Em modo dev (TTY ou redirecionado para arquivo), preserva o stream original.
    """
    if sys.stdout is None:
        sys.stdout = _DevNull()  # type: ignore[assignment]
    if sys.stderr is None:
        sys.stderr = _DevNull()  # type: ignore[assignment]


_initialized = False


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """
    Idempotente: chama uma vez no boot do main.py. Múltiplas chamadas são no-op.

    Devolve o logger raiz `videodelay` já configurado para uso imediato.
    """
    global _initialized
    if _initialized:
        return log

    _neutralize_streams()
    ensure_user_data_dir()  # garante que a pasta logs/ exista antes do handler

    log.setLevel(level)
    log.propagate = False  # evita duplicar para root logger

    fmt = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    # File handler (sempre)
    file_handler = RotatingFileHandler(
        log_path(),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    log.addHandler(file_handler)

    # Console handler — somente em dev com TTY. Quando frozen, sys.stdout
    # é _DevNull e não tem sentido escrever ali.
    if not is_frozen() and _stdout_is_tty():
        stream_handler = logging.StreamHandler(stream=sys.stdout)
        stream_handler.setFormatter(fmt)
        log.addHandler(stream_handler)

    _initialized = True
    log.info("=" * 60)
    log.info("Boot do app — frozen=%s, log=%s", is_frozen(), log_path())
    return log


def _stdout_is_tty() -> bool:
    try:
        return bool(sys.stdout and sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False


def stdout_is_tty() -> bool:
    """Versão pública para o main.py condicionar `display_status()`."""
    return _stdout_is_tty()
