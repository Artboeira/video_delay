"""Testes para modules/monitors.py — enumeração cross-platform."""
from __future__ import annotations

import unittest

from tests import _helpers  # noqa: F401 — ajusta sys.path

from modules.monitors import list_monitors, Monitor, _fallback


class MonitorsTests(unittest.TestCase):
    def test_list_monitors_never_empty(self):
        """A função pública sempre devolve pelo menos um monitor."""
        monitors = list_monitors()
        self.assertGreaterEqual(len(monitors), 1)

    def test_list_monitors_returns_monitor_dataclasses(self):
        for m in list_monitors():
            self.assertIsInstance(m, Monitor)
            self.assertIsInstance(m.index, int)
            self.assertIsInstance(m.name, str)
            self.assertIsInstance(m.width, int)
            self.assertIsInstance(m.height, int)
            self.assertIsInstance(m.primary, bool)

    def test_indices_are_sequential_from_zero(self):
        monitors = list_monitors()
        self.assertEqual(monitors[0].index, 0)
        for i, m in enumerate(monitors):
            self.assertEqual(m.index, i)

    def test_to_dict_serializable(self):
        import json
        monitors = [m.to_dict() for m in list_monitors()]
        # Não lança = serializável
        json.dumps(monitors)

    def test_fallback_returns_two_entries(self):
        fb = _fallback()
        self.assertEqual(len(fb), 2)
        self.assertTrue(fb[0].primary)
        self.assertFalse(fb[1].primary)


if __name__ == "__main__":
    unittest.main()
