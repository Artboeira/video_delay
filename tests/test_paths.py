"""Testa modules/paths.py — resolução de caminhos por plataforma."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import _helpers  # noqa: F401

from modules import paths


class IsFrozenTests(unittest.TestCase):
    def test_returns_false_in_dev(self):
        # No teste rodando do source, sys.frozen não existe.
        self.assertFalse(paths.is_frozen())


class UserDataDirTests(unittest.TestCase):
    def test_dev_mode_returns_project_root(self):
        result = paths.user_data_dir()
        # Em dev, deve apontar para a pasta do repo (parent de modules/)
        self.assertTrue((result / "modules").is_dir())
        self.assertTrue((result / "tests").is_dir())

    def test_frozen_mac_uses_application_support(self):
        # `as_posix()` normaliza separadores para `/` em qualquer SO, isolando o
        # teste do separador nativo do runner (Windows usa `\`).
        with patch.object(paths, "is_frozen", return_value=True), \
             patch.object(sys, "platform", "darwin"):
            result = paths.user_data_dir()
            self.assertIn("Library/Application Support/VideoDelay", result.as_posix())

    def test_frozen_windows_uses_appdata(self):
        with patch.object(paths, "is_frozen", return_value=True), \
             patch.object(sys, "platform", "win32"), \
             patch.dict(os.environ, {"APPDATA": r"C:\Users\foo\AppData\Roaming"}):
            result = paths.user_data_dir()
            self.assertTrue(result.name == "VideoDelay")
            self.assertIn("AppData", result.as_posix())

    def test_frozen_linux_uses_xdg(self):
        with patch.object(paths, "is_frozen", return_value=True), \
             patch.object(sys, "platform", "linux"), \
             patch.dict(os.environ, {"XDG_CONFIG_HOME": "/home/foo/.config"}):
            result = paths.user_data_dir()
            self.assertEqual(result.as_posix(), "/home/foo/.config/VideoDelay")


class DerivedPathsTests(unittest.TestCase):
    def test_config_path_is_user_data_dir_slash_config_json(self):
        self.assertEqual(paths.config_path().name, "config.json")
        self.assertEqual(paths.config_path().parent, paths.user_data_dir())

    def test_segments_dir_is_user_data_dir_slash_segments(self):
        self.assertEqual(paths.segments_dir().name, "segments")

    def test_log_path_is_under_logs_subdir(self):
        self.assertEqual(paths.log_path().parent.name, "logs")
        self.assertEqual(paths.log_path().name, "videodelay.log")

    def test_setup_flag_is_dot_setup_complete(self):
        self.assertEqual(paths.setup_flag_path().name, ".setup_complete")


class EnsureUserDataDirTests(unittest.TestCase):
    def test_creates_dir_and_logs_subdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "Fake" / "VideoDelay"
            with patch.object(paths, "user_data_dir", return_value=tmp_path):
                result = paths.ensure_user_data_dir()
            self.assertTrue(result.is_dir())
            self.assertTrue((tmp_path / "logs").is_dir())

    def test_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with patch.object(paths, "user_data_dir", return_value=tmp_path):
                paths.ensure_user_data_dir()
                paths.ensure_user_data_dir()
            # Não levanta — já existia


class BundledBinaryTests(unittest.TestCase):
    def test_dev_mode_falls_back_to_shutil_which(self):
        # Em dev sem bin/ embarcado, deve cair em shutil.which.
        # `ls` é universal no PATH em Mac/Linux/CI.
        if sys.platform != "win32":
            result = paths.bundled_binary("ls")
            self.assertTrue(result.endswith("/ls") or result == "ls")

    def test_missing_binary_returns_name_literal(self):
        # Sem bundle e sem PATH, devolve o name (subprocess vai falhar
        # com mensagem clara em vez de FileNotFoundError opaco).
        result = paths.bundled_binary("definitely-not-a-real-binary-xyz")
        self.assertEqual(result, "definitely-not-a-real-binary-xyz")

    def test_frozen_with_bundle_dir_returns_absolute_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            fake = bin_dir / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")
            fake.write_text("fake")
            fake.chmod(0o755)

            with patch.object(paths, "_bundle_bin_dir", return_value=bin_dir):
                result = paths.bundled_binary("ffmpeg")
            self.assertEqual(result, str(fake))


if __name__ == "__main__":
    unittest.main()
