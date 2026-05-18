"""
modules/capture.py — Gerencia a captura de vídeo via FFmpeg (DirectShow).

Captura o sinal da placa de captura e grava em segmentos de N segundos,
nomeados com timestamp (YYYYMMDD_HHMMSS.ts) para que o player saiba
exatamente quando cada segmento foi gravado.
"""

import subprocess
import threading
import time
import sys
from pathlib import Path
from datetime import datetime

from .paths import bundled_binary


class CaptureManager:
    def __init__(self, config: dict):
        self.config = config
        self.running = False
        self.error_message = ""
        self._stop_event = threading.Event()
        self._restart_event = threading.Event()
        self._process = None

    def request_restart(self):
        """Pede um reinício limpo do FFmpeg (usado quando config muda em runtime)."""
        self._restart_event.set()
        if self._process:
            try:
                self._process.terminate()
            except Exception:
                pass

    def _build_input_args(self) -> list:
        """
        Argumentos de entrada do FFmpeg.

        Três modos:
          • test_mode → fonte sintética `testsrc2` (multiplataforma, sem device)
          • Mac (não-teste) → AVFoundation; `capture_device` é o índice numérico
          • Win (não-teste) → DirectShow; `capture_device` é o nome da placa
        """
        if self.config.get("test_mode"):
            return [
                "-f", "lavfi",
                "-i", "testsrc2=size=1280x720:rate=30",
            ]

        device = self.config["capture_device"]

        if sys.platform == "darwin":
            # AVFoundation aceita índice ("0", "1") ou nome. `-an` evita
            # solicitar permissão de microfone (não capturamos áudio).
            return [
                "-f", "avfoundation",
                "-framerate", "30",
                "-pixel_format", "uyvy422",
                "-an",
                "-i", str(device),
            ]

        # Windows / Linux fallback (Linux só funciona em test_mode na prática)
        return [
            "-f", "dshow",
            "-rtbufsize", "100M",        # Buffer de entrada (evita drops)
            "-i", f"video={device}",
        ]

    def _build_ffmpeg_cmd(self) -> list:
        segment_time = self.config["segment_duration"]
        preset = self.config["video_quality"]["preset"]
        crf = self.config["video_quality"]["crf"]
        segments_dir = Path(self.config["segment_folder"])

        output_pattern = str(segments_dir / "%Y%m%d_%H%M%S.ts")

        return [
            bundled_binary("ffmpeg"),
            "-hide_banner",
            "-loglevel", "error",
            *self._build_input_args(),
            # Encoding
            "-c:v", "libx264",
            "-preset", preset,
            "-crf", str(crf),
            "-g", str(int(30 * segment_time)),  # GOP = 1 segmento
            "-sc_threshold", "0",
            "-force_key_frames", f"expr:gte(t,n_forced*{segment_time})",
            # Segmentação por timestamp
            "-f", "segment",
            "-segment_time", str(segment_time),
            "-segment_atclocktime", "1",
            "-strftime", "1",
            "-reset_timestamps", "1",
            output_pattern,
            "-y"
        ]

    def run(self):
        """Loop principal de captura. Reinicia automaticamente em caso de erro."""
        segments_dir = Path(self.config["segment_folder"])
        segments_dir.mkdir(exist_ok=True)

        while not self._stop_event.is_set():
            self.running = False
            self.error_message = "Iniciando captura..."

            try:
                cmd = self._build_ffmpeg_cmd()
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True
                )
                self.running = True
                self.error_message = ""

                # Lê stderr para detectar erros
                for line in self._process.stderr:
                    if self._stop_event.is_set():
                        break
                    line = line.strip()
                    if line:
                        self.error_message = line
                        self.running = False

                self._process.wait()

            except FileNotFoundError:
                self.error_message = "FFmpeg não encontrado no PATH"
                self.running = False
                self._stop_event.wait(5)
                continue

            except Exception as e:
                self.error_message = str(e)
                self.running = False

            if self._restart_event.is_set():
                # Reinício pedido externamente (config mudou) — sem espera longa.
                self._restart_event.clear()
                continue

            if not self._stop_event.is_set():
                self._stop_event.wait(3)  # Aguarda 3s antes de reiniciar

    def stop(self):
        self._stop_event.set()
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                self._process.kill()
        self.running = False
