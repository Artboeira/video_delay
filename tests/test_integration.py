"""
Teste de integração: roda o CaptureManager em modo de teste com FFmpeg real,
verifica que segmentos .ts são produzidos com timestamps corretos e que o
PlayerManager consegue selecioná-los respeitando o delay.

Pula automaticamente quando o `ffmpeg` não está no PATH — o teste é seguro
em CI sem dependências externas.
"""

import shutil
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from tests._helpers import make_config, TempSegments
from modules.capture import CaptureManager
from modules.player import PlayerManager
from modules.cleaner import CleanerManager
import threading


HAS_FFMPEG = shutil.which("ffmpeg") is not None


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg não encontrado no PATH")
class FFmpegTestModeIntegration(unittest.TestCase):
    """
    Sobe a captura em modo de teste por alguns segundos e verifica que:
    - pelo menos um segmento .ts foi gerado;
    - o nome bate com o padrão YYYYMMDD_HHMMSS.ts;
    - o tamanho do arquivo é > 0 (FFmpeg de fato escreveu).
    """

    def test_captures_synthetic_video_for_a_few_seconds(self):
        with TempSegments() as ts:
            config = make_config(
                segment_folder=str(ts.dir),
                segment_duration=2,   # acelera o teste — segmentos curtos
                test_mode=True,
            )
            capture = CaptureManager(config)
            thread = threading.Thread(target=capture.run, daemon=True)
            thread.start()
            try:
                # Aguarda 8s para garantir 2+ segmentos no disco
                deadline = time.time() + 8
                while time.time() < deadline:
                    segs = list(ts.dir.glob("*.ts"))
                    if len(segs) >= 2:
                        break
                    time.sleep(0.5)
                segs = sorted(ts.dir.glob("*.ts"))
                self.assertGreaterEqual(
                    len(segs), 1,
                    f"esperava ao menos 1 segmento, vi {[s.name for s in segs]}",
                )
                # Cada segmento tem nome parseável e tamanho > 0
                for s in segs:
                    self.assertRegex(s.name, r"^\d{8}_\d{6}\.ts$")
                    # O último pode estar sendo escrito, ignoramos o tamanho dele
                if len(segs) > 1:
                    for s in segs[:-1]:
                        self.assertGreater(
                            s.stat().st_size, 0,
                            f"segmento {s.name} ficou vazio",
                        )
            finally:
                capture.stop()
                thread.join(timeout=5)


class PlayerSelectsCapturedSegments(unittest.TestCase):
    """
    Sem precisar de FFmpeg: simula a "captura" criando arquivos com timestamps
    correspondentes a vários momentos do passado e verifica que o player
    seleciona apenas os que satisfazem o delay.

    Este é um teste end-to-end da lógica de delay sem necessidade de hardware
    ou binários externos — exatamente o caso de uso do "modo de teste robusto".
    """

    def test_player_advances_as_time_passes(self):
        with TempSegments() as ts:
            now = datetime.now()
            # Cria uma "história" de 5 minutos de gravação, 1 segmento a cada 5s.
            for offset in range(0, 300, 5):
                ts.create_at(now - timedelta(seconds=offset))

            # Delay = 120s. Tudo com timestamp <= now - 120s deve estar pronto.
            config = make_config(
                segment_folder=str(ts.dir),
                delay_seconds=120,
                segment_duration=5,
            )
            player = PlayerManager(config)
            ready = player._get_ready_segments()

            # 5 min de história menos 2 min de delay = 3 min de segmentos prontos.
            # 3 min / 5s = 36 segmentos esperados (com margem por arredondamento).
            self.assertGreater(len(ready), 30)
            self.assertLess(len(ready), 45)

            # Buffer deveria estar 100% cheio
            self.assertEqual(player._buffer_progress(), 1.0)

    def test_increasing_delay_reduces_ready_segments(self):
        """Aumentar o delay em tempo real deve reduzir a janela disponível."""
        with TempSegments() as ts:
            now = datetime.now()
            for offset in range(0, 300, 5):
                ts.create_at(now - timedelta(seconds=offset))

            config = make_config(
                segment_folder=str(ts.dir),
                delay_seconds=60,
                segment_duration=5,
            )
            player = PlayerManager(config)
            ready_60s = len(player._get_ready_segments())

            player.set_delay(240)  # exige segmentos > 4min de idade
            ready_240s = len(player._get_ready_segments())

            self.assertLess(ready_240s, ready_60s)


class CleanerRespectsBufferWindow(unittest.TestCase):
    """
    Sanity check: o cleaner não pode apagar segmentos que o player ainda
    precisa. Em uma config saudável, max_segment_age_seconds > delay_seconds.
    Este teste documenta essa invariante.
    """

    def test_cleaner_only_removes_truly_old_segments(self):
        with TempSegments() as ts:
            now = datetime.now()
            # Segmento dentro da janela do delay (não pode ser apagado)
            in_window = ts.create_at(now - timedelta(seconds=120))
            # Segmento velho o suficiente para limpeza
            old = ts.create_at(now - timedelta(seconds=900))

            config = make_config(
                segment_folder=str(ts.dir),
                delay_seconds=180,
                max_segment_age_seconds=600,
            )
            cleaner = CleanerManager(config)
            cleaner._clean()

            self.assertTrue(in_window.exists(), "cleaner apagou segmento ainda em uso")
            self.assertFalse(old.exists())


if __name__ == "__main__":
    unittest.main()
