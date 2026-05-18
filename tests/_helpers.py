"""
Helpers compartilhados entre os testes.

Inclui:
- Ajuste de sys.path para que `import modules` funcione sem instalar nada.
- Builder de config mínima válida.
- Criação de segmentos .ts falsos com timestamp arbitrário, para exercitar
  o PlayerManager e o CleanerManager sem depender de FFmpeg.
"""

from __future__ import annotations

import sys
import tempfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path


# Adiciona o diretório-raiz do projeto ao sys.path. Isso é o equivalente
# a rodar `python -m unittest` a partir da raiz, mas funciona também quando
# o usuário executa um arquivo de teste isoladamente.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def make_config(**overrides) -> dict:
    """Config válida mínima; overrides sobrescrevem chaves específicas."""
    base = {
        "delay_seconds": 120,
        "segment_duration": 5,
        "capture_device": "FakeDevice",
        "segment_folder": "segments",
        "max_segment_age_seconds": 600,
        "mpv_fullscreen_monitor": 0,
        "video_quality": {"preset": "ultrafast", "crf": 18},
    }
    base.update(overrides)
    return base


class TempSegments:
    """
    Context manager que cria uma pasta temporária e oferece um helper para
    fabricar arquivos .ts com timestamp no nome (formato esperado pelo player).

        with TempSegments() as ts:
            ts.create_at(datetime.now() - timedelta(seconds=300))
            ts.create_at(datetime.now() - timedelta(seconds=200))
            ...
    """

    def __init__(self):
        self.dir: Path | None = None

    def __enter__(self) -> "TempSegments":
        self.dir = Path(tempfile.mkdtemp(prefix="video-delay-test-"))
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.dir and self.dir.exists():
            shutil.rmtree(self.dir, ignore_errors=True)

    def create_at(self, when: datetime, content: bytes = b"FAKE") -> Path:
        """Cria um segmento .ts com timestamp `when` no nome."""
        assert self.dir is not None
        name = when.strftime("%Y%m%d_%H%M%S") + ".ts"
        path = self.dir / name
        path.write_bytes(content)
        return path

    def create_series(
        self, count: int, *, step_seconds: int = 5, oldest_offset: int = 0
    ) -> list[Path]:
        """
        Cria `count` segmentos consecutivos espaçados de `step_seconds`,
        com o mais antigo posicionado `oldest_offset` segundos atrás de agora.
        """
        now = datetime.now()
        return [
            self.create_at(now - timedelta(seconds=oldest_offset - i * step_seconds))
            for i in range(count)
        ]
