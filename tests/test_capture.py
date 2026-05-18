"""Testa a montagem do comando FFmpeg pelo CaptureManager."""

import sys
import unittest
from unittest.mock import patch

from tests._helpers import make_config
from modules.capture import CaptureManager


def args_after(cmd: list, flag: str) -> str | None:
    """Retorna o próximo argumento depois de `flag`, ou None."""
    try:
        idx = cmd.index(flag)
        return cmd[idx + 1]
    except (ValueError, IndexError):
        return None


class FFmpegCommandTests(unittest.TestCase):
    # `bundled_binary` faz shutil.which; patcher sys.platform globalmente
    # quebra Windows-only paths dentro de shutil. Patcheamos o resolver para
    # devolver um literal e isolamos só o branch de _build_input_args.
    def _patch_platform(self, name):
        return patch("modules.capture.sys.platform", name)

    def _patch_bin(self):
        return patch("modules.capture.bundled_binary", return_value="ffmpeg")

    def test_production_mode_windows_uses_dshow(self):
        config = make_config(capture_device="Elgato HD60 S")
        with self._patch_platform("win32"), self._patch_bin():
            cmd = CaptureManager(config)._build_ffmpeg_cmd()

        idx = cmd.index("-f")
        self.assertEqual(cmd[idx + 1], "dshow")
        self.assertEqual(args_after(cmd, "-i"), "video=Elgato HD60 S")
        self.assertIn("-rtbufsize", cmd)

    def test_production_mode_mac_uses_avfoundation(self):
        config = make_config(capture_device="0")
        with self._patch_platform("darwin"), self._patch_bin():
            cmd = CaptureManager(config)._build_ffmpeg_cmd()

        idx = cmd.index("-f")
        self.assertEqual(cmd[idx + 1], "avfoundation")
        self.assertEqual(args_after(cmd, "-i"), "0")
        # Sem áudio — não pedimos permissão de microfone
        self.assertIn("-an", cmd)
        # Framerate explícito (avfoundation precisa)
        self.assertEqual(args_after(cmd, "-framerate"), "30")

    def test_test_mode_uses_lavfi_testsrc(self):
        config = make_config(test_mode=True)
        cmd = CaptureManager(config)._build_ffmpeg_cmd()

        # Input format = lavfi
        idx = cmd.index("-f")
        self.assertEqual(cmd[idx + 1], "lavfi")

        # Input source é testsrc2 (não depende de device)
        i_arg = args_after(cmd, "-i")
        self.assertIsNotNone(i_arg)
        self.assertIn("testsrc2", i_arg)

        # rtbufsize NÃO faz sentido em fonte sintética
        self.assertNotIn("-rtbufsize", cmd)

    def test_encoding_params_propagate_from_config(self):
        config = make_config(
            video_quality={"preset": "fast", "crf": 23},
            segment_duration=10,
        )
        cmd = CaptureManager(config)._build_ffmpeg_cmd()

        self.assertEqual(args_after(cmd, "-preset"), "fast")
        self.assertEqual(args_after(cmd, "-crf"), "23")
        self.assertEqual(args_after(cmd, "-segment_time"), "10")

    def test_gop_is_derived_from_segment_duration(self):
        """O GOP precisa cobrir um segmento inteiro para garantir keyframe na borda."""
        config = make_config(segment_duration=5)
        cmd = CaptureManager(config)._build_ffmpeg_cmd()
        # GOP = 30fps * 5s = 150
        self.assertEqual(args_after(cmd, "-g"), "150")

        config = make_config(segment_duration=10)
        cmd = CaptureManager(config)._build_ffmpeg_cmd()
        self.assertEqual(args_after(cmd, "-g"), "300")

    def test_output_pattern_uses_segment_folder(self):
        config = make_config(segment_folder="my_segments")
        cmd = CaptureManager(config)._build_ffmpeg_cmd()
        # Último argumento posicional contém o padrão de saída
        # (antes do -y final)
        self.assertIn("my_segments", " ".join(cmd))
        self.assertIn("%Y%m%d_%H%M%S.ts", " ".join(cmd))


if __name__ == "__main__":
    unittest.main()
