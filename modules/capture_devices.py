"""
modules/capture_devices.py — Enumeração cross-platform de dispositivos de captura.

Substitui o antigo `list_devices.py` (que só funcionava no Windows). Agora o
painel/wizard chama `list_capture_devices()` para popular o dropdown com
exatamente as placas que o operador tem ligadas — sem precisar digitar nada.

Estratégia:
  • Win  → `ffmpeg -f dshow -list_devices true -i dummy`, parseia stderr
  • Mac  → `ffmpeg -f avfoundation -list_devices true -i ""`, parseia stderr
  • Linux → vazio (não suportado nesta rodada)

O `platform_id` retornado é exatamente o que vai entrar em `config.capture_device`
e ser passado para o FFmpeg em `_build_input_args` do `CaptureManager`:
  • Win: string (nome do device DirectShow)
  • Mac: string com índice numérico (ex. "0")

Tolerante a falhas: em qualquer erro retorna lista vazia. UI mostra opção de
"modo de teste" sempre, então o usuário nunca fica encurralado.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, asdict

from .paths import bundled_binary


@dataclass(frozen=True)
class CaptureDevice:
    """Descreve uma placa/câmera detectada pelo SO."""
    index: int
    name: str           # Exibição amigável no painel
    platform_id: str    # Identificador a passar para o FFmpeg em runtime

    def to_dict(self) -> dict:
        return asdict(self)


def list_capture_devices() -> list[CaptureDevice]:
    """Lista dispositivos de captura disponíveis. Nunca lança."""
    try:
        if sys.platform == "win32":
            return _list_dshow()
        if sys.platform == "darwin":
            return _list_avfoundation()
    except Exception:
        return []
    return []


# ──────────────────────────────────────────────────────────────────────
#  Windows — DirectShow
# ──────────────────────────────────────────────────────────────────────

_DSHOW_DEVICE_RE = re.compile(r'"([^"]+)"\s*\(video\)?', re.IGNORECASE)


def _list_dshow() -> list[CaptureDevice]:
    cmd = [
        bundled_binary("ffmpeg"),
        "-hide_banner",
        "-f", "dshow",
        "-list_devices", "true",
        "-i", "dummy",
    ]
    out = _run_ffmpeg(cmd)
    devices: list[CaptureDevice] = []
    in_video_section = False
    for line in out.splitlines():
        if "DirectShow video devices" in line:
            in_video_section = True
            continue
        if "DirectShow audio devices" in line:
            in_video_section = False
            continue
        if not in_video_section:
            continue
        # Ignora "Alternative name" lines
        if "Alternative name" in line:
            continue
        m = re.search(r'"([^"]+)"', line)
        if m:
            name = m.group(1)
            devices.append(CaptureDevice(
                index=len(devices),
                name=name,
                platform_id=name,  # dshow usa o próprio nome como ID
            ))
    return devices


# ──────────────────────────────────────────────────────────────────────
#  macOS — AVFoundation
# ──────────────────────────────────────────────────────────────────────

# Formato típico: "[AVFoundation indev @ 0x...] [0] Câmera do MacBook Pro"
_AVF_LINE_RE = re.compile(
    r"\[AVFoundation\s+indev[^\]]*\]\s+\[(\d+)\]\s+(.+)$"
)


def _list_avfoundation() -> list[CaptureDevice]:
    cmd = [
        bundled_binary("ffmpeg"),
        "-hide_banner",
        "-f", "avfoundation",
        "-list_devices", "true",
        "-i", "",
    ]
    out = _run_ffmpeg(cmd)
    devices: list[CaptureDevice] = []
    in_video_section = False
    for line in out.splitlines():
        if "AVFoundation video devices" in line:
            in_video_section = True
            continue
        if "AVFoundation audio devices" in line:
            in_video_section = False
            continue
        if not in_video_section:
            continue
        m = _AVF_LINE_RE.search(line)
        if m:
            idx_str, name = m.group(1), m.group(2).strip()
            devices.append(CaptureDevice(
                index=int(idx_str),
                name=name,
                platform_id=idx_str,  # avfoundation usa índice numérico
            ))
    return devices


# ──────────────────────────────────────────────────────────────────────
#  Helper
# ──────────────────────────────────────────────────────────────────────

def _run_ffmpeg(cmd: list[str]) -> str:
    """
    FFmpeg sempre escreve o list_devices em stderr e termina com erro 1
    (não há arquivo de entrada). Capturamos ambos e ignoramos o exit code.
    """
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return (proc.stdout or "") + (proc.stderr or "")
