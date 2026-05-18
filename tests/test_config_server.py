"""Testes para modules/config_server.py — servidor HTTP local do painel."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from tests import _helpers  # noqa: F401

from modules import CaptureManager, PlayerManager, CleanerManager, ConfigServer, ServerState


class _Harness:
    """Sobe um ConfigServer apontando para managers reais (não iniciados)."""
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="vd-test-")
        self.config_path = Path(self.tmp.name) / "config.json"
        self.config = _helpers.make_config(
            segment_folder=str(Path(self.tmp.name) / "segments"),
            test_mode=True,
        )
        Path(self.config["segment_folder"]).mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")

        self.capture = CaptureManager(self.config)
        self.player = PlayerManager(self.config)
        self.cleaner = CleanerManager(self.config)

        self.shutdown_event = threading.Event()
        self.state = ServerState(
            config=self.config,
            capture=self.capture, player=self.player, cleaner=self.cleaner,
            config_path=self.config_path,
            shutdown_event=self.shutdown_event,
        )
        self.server = ConfigServer(self.state)
        self.server.start()

    def url(self, path: str = "") -> str:
        return self.server.url.rstrip("/") + path

    def close(self):
        self.server.stop()
        self.tmp.cleanup()


def _get(url: str) -> tuple[int, dict | str]:
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            ctype = r.headers.get("Content-Type", "")
            body = r.read()
            if "json" in ctype:
                return r.status, json.loads(body.decode("utf-8"))
            return r.status, body.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def _post_json(url: str, payload: dict) -> tuple[int, dict | str]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=2) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


class ConfigServerEndpointsTests(unittest.TestCase):
    def setUp(self):
        self.h = _Harness()

    def tearDown(self):
        self.h.close()

    def test_get_config_returns_current_state(self):
        status, body = _get(self.h.url("/api/config"))
        self.assertEqual(status, 200)
        self.assertEqual(body["delay_seconds"], 120)
        self.assertTrue(body["test_mode"])

    def test_get_monitors_returns_list(self):
        status, body = _get(self.h.url("/api/monitors"))
        self.assertEqual(status, 200)
        self.assertIsInstance(body, list)
        self.assertGreaterEqual(len(body), 1)

    def test_get_status_returns_snapshot(self):
        status, body = _get(self.h.url("/api/status"))
        self.assertEqual(status, 200)
        for key in ("capture_running", "player_status", "buffer_progress",
                    "deleted_count", "delay_seconds"):
            self.assertIn(key, body)

    def test_post_config_updates_delay(self):
        status, body = _post_json(self.h.url("/api/config"), {"delay_seconds": 60})
        self.assertEqual(status, 200)
        self.assertEqual(body["delay_seconds"], 60)
        # Persistido em disco
        on_disk = json.loads(self.h.config_path.read_text())
        self.assertEqual(on_disk["delay_seconds"], 60)
        # Player foi atualizado
        self.assertEqual(self.h.player.get_delay(), 60)

    def test_post_config_rejects_too_small_delay(self):
        status, body = _post_json(self.h.url("/api/config"), {"delay_seconds": 5})
        self.assertEqual(status, 400)
        self.assertIn("delay_seconds", body["error"])

    def test_post_config_rejects_max_age_below_delay(self):
        status, body = _post_json(
            self.h.url("/api/config"),
            {"delay_seconds": 700, "max_segment_age_seconds": 600},
        )
        self.assertEqual(status, 400)
        self.assertIn("max_segment_age_seconds", body["error"])

    def test_post_config_rejects_crf_out_of_range(self):
        status, body = _post_json(
            self.h.url("/api/config"),
            {"video_quality": {"preset": "ultrafast", "crf": 99}},
        )
        self.assertEqual(status, 400)
        self.assertIn("crf", body["error"])

    def test_post_config_ignores_unknown_fields(self):
        # Campos fora do whitelist são descartados silenciosamente — não viram chave.
        status, body = _post_json(
            self.h.url("/api/config"),
            {"hax": "bypass", "delay_seconds": 90},
        )
        self.assertEqual(status, 200)
        self.assertNotIn("hax", body)
        self.assertEqual(body["delay_seconds"], 90)

    def test_static_index_html_served(self):
        status, body = _get(self.h.url("/"))
        self.assertEqual(status, 200)
        self.assertIn("<!DOCTYPE html>", body)
        self.assertIn("Video Delay", body)

    def test_static_path_traversal_blocked(self):
        status, body = _get(self.h.url("/../config.json"))
        # Os servidores HTTP da stdlib já normalizam ".." antes de chegar.
        # De qualquer forma a resposta não pode vazar o config.json do projeto.
        self.assertIn(status, (404, 400))

    def test_shutdown_endpoint_sets_event(self):
        self.assertFalse(self.h.shutdown_event.is_set())
        status, body = _post_json(self.h.url("/api/shutdown"), {})
        self.assertEqual(status, 200)
        self.assertTrue(self.h.shutdown_event.is_set())


class WizardEndpointTests(unittest.TestCase):
    def setUp(self):
        self.h = _Harness()
        # config_server.py importa setup_flag_path direto — patch no namespace dele
        # E também no paths para o handler que serve /api/setup-status
        from modules import config_server, paths
        self.flag_path = Path(self.h.tmp.name) / ".setup_complete"
        self._patches = [
            patch.object(config_server, "setup_flag_path",
                         return_value=self.flag_path),
            patch.object(paths, "setup_flag_path",
                         return_value=self.flag_path),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.h.close()

    def test_setup_status_incomplete_with_placeholder_device(self):
        # config tem capture_device='FakeDevice' do helper, não placeholder
        # mas precisamos forçar placeholder para o teste fazer sentido
        self.h.state.config["capture_device"] = "YOUR_CAPTURE_CARD_NAME"
        status, body = _get(self.h.url("/api/setup-status"))
        self.assertEqual(status, 200)
        self.assertFalse(body["complete"])

    def test_setup_status_complete_after_flag_and_real_device(self):
        self.flag_path.touch()
        # capture_device já é "FakeDevice" do _Harness — não-placeholder
        status, body = _get(self.h.url("/api/setup-status"))
        self.assertEqual(status, 200)
        self.assertTrue(body["complete"])

    def test_capture_devices_endpoint_returns_list(self):
        # Mocka list_capture_devices para não depender do SO
        from modules import config_server
        from modules.capture_devices import CaptureDevice
        fake = [CaptureDevice(0, "Fake Camera", "0")]
        with patch.object(config_server, "list_capture_devices", return_value=fake):
            status, body = _get(self.h.url("/api/capture-devices"))
        self.assertEqual(status, 200)
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["name"], "Fake Camera")

    def test_setup_complete_creates_flag_and_applies_config(self):
        status, body = _post_json(self.h.url("/api/setup-complete"), {
            "delay_seconds": 45,
            "capture_device": "Fake",
            "test_mode": False,
        })
        self.assertEqual(status, 200)
        self.assertTrue(self.flag_path.exists())
        self.assertEqual(self.h.state.config["delay_seconds"], 45)


class ConfigServerCaptureRestartTests(unittest.TestCase):
    """Mudanças em campos que afetam o FFmpeg devem solicitar restart."""

    def setUp(self):
        self.h = _Harness()
        # Marker para detectar request_restart() sem subir captura real
        self.h.capture._restart_called = False
        orig = self.h.capture.request_restart
        def spy():
            self.h.capture._restart_called = True
            orig()
        self.h.capture.request_restart = spy

    def tearDown(self):
        self.h.close()

    def test_delay_change_does_not_restart_capture(self):
        _post_json(self.h.url("/api/config"), {"delay_seconds": 60})
        self.assertFalse(self.h.capture._restart_called)

    def test_test_mode_change_restarts_capture(self):
        _post_json(self.h.url("/api/config"), {"test_mode": False})
        self.assertTrue(self.h.capture._restart_called)


if __name__ == "__main__":
    unittest.main()
