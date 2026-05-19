"""Testa parsing de saída do ffmpeg em capture_devices.py."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from tests import _helpers  # noqa: F401

from modules import capture_devices
from modules.capture_devices import (
    CaptureDevice, list_capture_devices, _list_dshow, _list_avfoundation,
)


# Formato FFmpeg 4-7: prefixo [dshow @ ...] e seções com cabeçalho explícito.
_DSHOW_FIXTURE = """\
[dshow @ 0x123] DirectShow video devices (some options omitted):
[dshow @ 0x123]  "Elgato HD60 S+" (video)
[dshow @ 0x123]     Alternative name "@device_pnp_\\\\?\\usb#vid_0fd9..."
[dshow @ 0x123]  "USB Video" (video)
[dshow @ 0x123] DirectShow audio devices
[dshow @ 0x123]  "Microphone (Realtek)" (audio)
"""

# Formato FFmpeg 8.x: prefixo [in#0 @ ...], sem cabeçalho de seção. Capturado
# da saída real de uma placa VEDO-VDV66003 em Windows 11 (2026-05). O parser
# tem que sobreviver à transição sem regressão.
_DSHOW_FIXTURE_FFMPEG_8 = """\
[in#0 @ 0000028de89e87c0] "NDI Webcam Video 1" (video)
[in#0 @ 0000028de89e87c0]   Alternative name "@device_pnp_\\\\?\\root#media#0001#vidsource0"
[in#0 @ 0000028de89e87c0] "Integrated Webcam" (video)
[in#0 @ 0000028de89e87c0]   Alternative name "@device_pnp_\\\\?\\usb#vid_0c45..."
[in#0 @ 0000028de89e87c0] "VEDO-VDV66003" (video)
[in#0 @ 0000028de89e87c0]   Alternative name "@device_pnp_\\\\?\\usb#vid_048d..."
[in#0 @ 0000028de89e87c0] "OBS Virtual Camera" (none)
[in#0 @ 0000028de89e87c0] "Microfone (VEDO-VDV66003)" (audio)
[in#0 @ 0000028de89e87c0] "HDMI (2- VEDO-VDV66003)" (audio)
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

    def test_parses_ffmpeg_8_format_without_section_header(self):
        """FFmpeg 8.x mudou o prefixo de [dshow @ ...] para [in#0 @ ...] e
        deixou de emitir o cabeçalho 'DirectShow video devices'. O parser
        deve identificar dispositivos de vídeo pelo sufixo (video) em cada
        linha, sem depender de cabeçalhos de seção."""
        with patch.object(capture_devices, "_run_ffmpeg",
                          return_value=_DSHOW_FIXTURE_FFMPEG_8):
            devices = _list_dshow()
        names = [d.name for d in devices]
        self.assertIn("VEDO-VDV66003", names)
        self.assertIn("Integrated Webcam", names)
        self.assertIn("NDI Webcam Video 1", names)

    def test_ffmpeg_8_excludes_audio_and_none_devices(self):
        """O sufixo (audio) e (none) devem ser ignorados — só (video) entra."""
        with patch.object(capture_devices, "_run_ffmpeg",
                          return_value=_DSHOW_FIXTURE_FFMPEG_8):
            devices = _list_dshow()
        names = [d.name for d in devices]
        self.assertNotIn("Microfone (VEDO-VDV66003)", names)
        self.assertNotIn("HDMI (2- VEDO-VDV66003)", names)
        self.assertNotIn("OBS Virtual Camera", names)


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
