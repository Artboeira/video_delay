"""
modules/monitors.py — Enumeração de monitores cross-platform via stdlib.

A UI de configuração precisa listar os monitores disponíveis para que o
operador escolha em qual deles o playback fullscreen vai aparecer. O MPV
aceita um índice numérico em `--screen=N` / `--fs-screen=N`, então só
precisamos saber: quantos monitores existem, qual é o primário e (idealmente)
nome/resolução para cada um.

Sem dependências externas:
  - Windows: ctypes + EnumDisplayMonitors / GetMonitorInfoW (user32)
  - macOS:   system_profiler SPDisplaysDataType -json (binário do SO)
  - Linux:   xrandr --query (fallback; melhor esforço — ausência ⇒ lista genérica)

Falha sempre cai num fallback genérico que devolve 2 monitores ([0, 1])
para que a UI continue funcionando — o MPV resolve em runtime.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class Monitor:
    index: int
    name: str
    width: int
    height: int
    primary: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _fallback() -> list[Monitor]:
    """Lista genérica usada quando a enumeração nativa falha."""
    return [
        Monitor(index=0, name="Monitor 0 (primário)", width=0, height=0, primary=True),
        Monitor(index=1, name="Monitor 1 (secundário)", width=0, height=0, primary=False),
    ]


# ──────────────────────────────────────────────────────────────────────
#  Windows
# ──────────────────────────────────────────────────────────────────────

def _list_windows() -> list[Monitor]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
            ("szDevice", wintypes.WCHAR * 32),
        ]

    MONITORINFOF_PRIMARY = 0x00000001
    handles: list = []

    def _cb(hmon, _hdc, _rect, _lparam):
        handles.append(hmon)
        return 1

    user32.EnumDisplayMonitors(0, 0, MONITORENUMPROC(_cb), 0)

    monitors: list[Monitor] = []
    # Ordena com o primário primeiro para alinhar com a convenção do MPV
    # (--screen=0 = primário na maioria dos drivers).
    primaries, others = [], []
    for h in handles:
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if not user32.GetMonitorInfoW(h, ctypes.byref(info)):
            continue
        is_primary = bool(info.dwFlags & MONITORINFOF_PRIMARY)
        rc = info.rcMonitor
        width = rc.right - rc.left
        height = rc.bottom - rc.top
        name = info.szDevice or "Display"
        entry = (name, width, height, is_primary)
        (primaries if is_primary else others).append(entry)

    ordered = primaries + others
    for i, (name, w, h, is_primary) in enumerate(ordered):
        label = f"{name} — {w}×{h}" + ("  (primário)" if is_primary else "")
        monitors.append(Monitor(index=i, name=label, width=w, height=h, primary=is_primary))

    return monitors or _fallback()


# ──────────────────────────────────────────────────────────────────────
#  macOS
# ──────────────────────────────────────────────────────────────────────

def _list_macos() -> list[Monitor]:
    if not shutil.which("system_profiler"):
        return _fallback()

    try:
        proc = subprocess.run(
            ["system_profiler", "SPDisplaysDataType", "-json"],
            capture_output=True, text=True, timeout=5,
        )
        data = json.loads(proc.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return _fallback()

    monitors: list[Monitor] = []
    for gpu in data.get("SPDisplaysDataType", []):
        for d in gpu.get("spdisplays_ndrvs", []):
            name = d.get("_name", "Display")
            res = d.get("_spdisplays_resolution") or d.get("spdisplays_resolution") or ""
            # Ex.: "2560 x 1600 @ 60.00Hz" → 2560 / 1600
            w, h = 0, 0
            try:
                head = res.split("@")[0].strip()
                parts = head.split("x")
                if len(parts) >= 2:
                    w = int(parts[0].strip())
                    h = int(parts[1].strip())
            except (ValueError, AttributeError):
                pass
            is_primary = d.get("spdisplays_main") == "spdisplays_yes"
            label = f"{name}" + (f" — {w}×{h}" if w else "") + ("  (primário)" if is_primary else "")
            monitors.append(Monitor(index=len(monitors), name=label,
                                    width=w, height=h, primary=is_primary))

    if not monitors:
        return _fallback()

    # Garante que o primário fique no índice 0 (convenção MPV)
    monitors.sort(key=lambda m: (not m.primary, m.index))
    monitors = [Monitor(index=i, name=m.name, width=m.width,
                        height=m.height, primary=m.primary)
                for i, m in enumerate(monitors)]
    return monitors


# ──────────────────────────────────────────────────────────────────────
#  Linux (fallback útil em dev)
# ──────────────────────────────────────────────────────────────────────

def _list_linux() -> list[Monitor]:
    if not shutil.which("xrandr"):
        return _fallback()
    try:
        out = subprocess.check_output(["xrandr", "--query"], text=True, timeout=5)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return _fallback()

    monitors: list[Monitor] = []
    for line in out.splitlines():
        # Ex.: "HDMI-1 connected primary 2560x1440+0+0 ..."
        if " connected" not in line:
            continue
        tokens = line.split()
        name = tokens[0]
        primary = "primary" in tokens
        width = height = 0
        for tok in tokens:
            if "x" in tok and "+" in tok:
                head = tok.split("+", 1)[0]
                try:
                    width, height = (int(x) for x in head.split("x"))
                except ValueError:
                    pass
                break
        label = f"{name}" + (f" — {width}×{height}" if width else "") + ("  (primário)" if primary else "")
        monitors.append(Monitor(index=len(monitors), name=label,
                                width=width, height=height, primary=primary))

    return monitors or _fallback()


# ──────────────────────────────────────────────────────────────────────
#  API pública
# ──────────────────────────────────────────────────────────────────────

def list_monitors() -> list[Monitor]:
    """Enumera monitores do sistema. Nunca lança — sempre retorna >= 1 item."""
    try:
        if sys.platform == "win32":
            return _list_windows()
        if sys.platform == "darwin":
            return _list_macos()
        return _list_linux()
    except Exception:
        return _fallback()
