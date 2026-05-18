"""Testa parsing de saída do ffmpeg em capture_devices.py."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from tests import _helpers  # noqa: F401

from modules import capture_devices
from modules.capture_devices import (
    CaptureDevice, list_capture_devices, _list_dshow, _list_avfoundation,
)


_DSHOW_FIXTURE = """\
[dshow @ 0x123] DirectShow video devices (some options omitted):
[dshow @ 0x123]  "Elgato HD60 S+"
[dshow @ 0x123]     Alternative name "@device_pnp_\\\\?\\usb#vid_0fd9..."
[dshow @ 0x123]  "USB Video"
[dshow @ 0x123] DirectShow audio devices
[dshow @ 0x123]  "Microphone (Realtek)"
"""

_AVFOUNDATION_FIXTURE = """\
[AVFoundation indev @ 0x1234] AVFoundation video devices:
[AVFoundation indev @ 0x1234] [0] FaceTime HD Camera
[AVFoundation indev @ 0x1234] [1] Elgato HD60 S+
[AVFoundation indev @ 0x1234] [2] Capture screen 0
[AVFoundation indev @ 0x1234] AVFoundation audio devices:
[AVFoundation indev @ 0x1234] [0] Built-in Microphone
"""


class DshowParserTests(unittest.TestCase):
    def test_extracts_video_devices_only(self):
        with patch.object(capture_devices, "_run_ffmpeg", return_value=_DSHOW_FIXTURE):
            devices = _list_dshow()
        names = [d.name for d in devices]
        self.assertIn("Elgato HD60 S+", names)
        self.assertIn("USB Video", names)
        self.assertNotIn("Microphone (Realtek)", names)

    def test_ignores_alternative_name_lines(self):
        with patch.object(capture_devices, "_run_ffmpeg", return_value=_DSHOW_FIXTURE):
            devices = _list_dshow()
        for d in devices:
            self.assertNotIn("@device_pnp", d.name)

    def test_platform_id_is_the_device_name(self):
        with patch.object(capture_devices, "_run_ffmpeg", return_value=_DSHOW_FIXTURE):
            devices = _list_dshow()
        self.assertEqual(devices[0].platform_id, devices[0].name)


class AvfoundationParserTests(unittest.TestCase):
    def test_extracts_indexed_video_devices(self):
        with patch.object(capture_devices, "_run_ffmpeg", return_value=_AVFOUNDATION_FIXTURE):
            devices = _list_avfoundation()
        self.assertEqual(len(devices), 3)
        self.assertEqual(devices[0].name, "FaceTime HD Camera")
        self.assertEqual(devices[1].name, "Elgato HD60 S+")

    def test_ignores_audio_section(self):
        with patch.object(capture_devices, "_run_ffmpeg", return_value=_AVFOUNDATION_FIXTURE):
            devices = _list_avfoundation()
        names = [d.name for d in devices]
        self.assertNotIn("Built-in Microphone", names)

    def test_platform_id_is_numeric_string(self):
        with patch.object(capture_devices, "_run_ffmpeg", return_value=_AVFOUNDATION_FIXTURE):
            devices = _list_avfoundation()
        self.assertEqual(devices[0].platform_id, "0")
        self.assertEqual(devices[1].platform_id, "1")
        self.assertEqual(devices[2].platform_id, "2")


class ListCaptureDevicesTests(unittest.TestCase):
    def test_returns_list_even_on_failure(self):
        with patch.object(capture_devices, "_run_ffmpeg", return_value=""):
            result = list_capture_devices()
        self.assertEqual(result, [])

    def test_dataclass_serializes_via_to_dict(self):
        d = CaptureDevice(index=0, name="X", platform_id="0")
        self.assertEqual(d.to_dict(), {"index": 0, "name": "X", "platform_id": "0"})


if __name__ == "__main__":
    unittest.main()
