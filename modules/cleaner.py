"""
modules/cleaner.py — Remove segmentos antigos do disco.

Mantém apenas os segmentos necessários para o buffer de delay,
mais uma margem de segurança. Evita encher o disco em longas execuções.
"""

import threading
import time
from pathlib import Path
from datetime import datetime, timedelta


class CleanerManager:
    def __init__(self, config: dict):
        self.config = config
        self._stop_event = threading.Event()
        self.deleted_count = 0

    def run(self):
        """Loop de limpeza: roda a cada 30 segundos."""
        while not self._stop_event.is_set():
            self._clean()
            self._stop_event.wait(30)

    def _clean(self):
        segments_dir = Path(self.config["segment_folder"])
        max_age = self.config.get("max_segment_age_seconds", 240)
        cutoff = datetime.now() - timedelta(seconds=max_age)

        for seg in segments_dir.glob("*.ts"):
            try:
                seg_time = datetime.strptime(seg.stem, "%Y%m%d_%H%M%S")
                if seg_time < cutoff:
                    seg.unlink(missing_ok=True)
                    self.deleted_count += 1
            except (ValueError, OSError):
                continue

    def purge_all(self) -> int:
        """
        Apaga TODOS os .ts da pasta segments. Retorna quantos foram apagados.

        Usado no startup e no shutdown — não filtra por idade nem por nome.
        Não toca em `deleted_count` (reservado para a limpeza periódica de
        `_clean()`, que é a métrica de sessão exibida no painel).
        """
        segments_dir = Path(self.config["segment_folder"])
        removed = 0
        for seg in segments_dir.glob("*.ts"):
            try:
                seg.unlink(missing_ok=True)
                removed += 1
            except OSError:
                continue
        return removed

    def stop(self):
        self._stop_event.set()
