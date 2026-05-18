"""Testa helpers de UI e validação do main.py."""

import io
import json
import unittest
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tests._helpers import make_config


# Importa main como módulo. Em não-Windows, msvcrt é shimado como None
# (ver main.py); o import deve funcionar em qualquer plataforma.
import main
from modules import paths


class FormatDelayTests(unittest.TestCase):
    def test_formats_seconds_with_zero_padding(self):
        self.assertEqual(main.format_delay(0), "0min 00s")
        self.assertEqual(main.format_delay(5), "0min 05s")
        self.assertEqual(main.format_delay(60), "1min 00s")
        self.assertEqual(main.format_delay(125), "2min 05s")
        self.assertEqual(main.format_delay(3661), "61min 01s")


class ValidateConfigTests(unittest.TestCase):
    def test_rejects_placeholder_capture_device(self):
        """Contrato atual: retorna False (deixa main abrir o painel para correção)."""
        config = make_config(capture_device="YOUR_CAPTURE_CARD_NAME")
        with redirect_stdout(io.StringIO()):
            result = main.validate_config(config)
        self.assertFalse(result)

    def test_accepts_valid_capture_device(self):
        config = make_config(capture_device="Elgato HD60 S")
        self.assertTrue(main.validate_config(config))

    def test_test_mode_bypasses_device_check(self):
        """Em modo de teste o nome da placa é irrelevante."""
        config = make_config(
            capture_device="YOUR_CAPTURE_CARD_NAME",
            test_mode=True,
        )
        self.assertTrue(main.validate_config(config))


class LoadConfigTests(unittest.TestCase):
    def test_loads_json_from_disk(self):
        import tempfile

        data = make_config(delay_seconds=42)
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(data, f)
            path = Path(f.name)

        try:
            # `config_path` é importado em main; patch no namespace local
            with patch.object(main, "config_path", return_value=path):
                loaded = main.load_config()
            self.assertEqual(loaded["delay_seconds"], 42)
        finally:
            path.unlink(missing_ok=True)

    def test_exits_when_config_missing(self):
        ghost = Path("/nonexistent/__nope__.json")
        with patch.object(main, "config_path", return_value=ghost):
            with self.assertRaises(SystemExit):
                main.load_config()


if __name__ == "__main__":
    unittest.main()
