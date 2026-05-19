r"""
modules/player.py — Playback com delay usando MPV.

Aguarda o buffer de segmentos encher (delay configurado), então começa
a reproduzir os segmentos na ordem correta, mantendo o MPV sempre
alimentado com os próximos segmentos via IPC.

Canal IPC:
  - Windows: named pipe  \\.\pipe\mpv-delay-system
  - macOS/Linux: UNIX domain socket em $TMPDIR/mpv-delay-system.sock
"""

import subprocess
import sys
import threading
import time
import json
import os
import socket
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

from .paths import bundled_binary


_IS_WINDOWS = sys.platform == "win32"

# Caminho do canal IPC do MPV. No Windows usa named pipe; em Unix, socket UNIX.
# O MPV aceita ambos via --input-ipc-server=<caminho>.
if _IS_WINDOWS:
    MPV_PIPE = r"\\.\pipe\mpv-delay-system"
else:
    MPV_PIPE = str(Path(tempfile.gettempdir()) / "mpv-delay-system.sock")


def _send_mpv(command: list) -> bool:
    """Envia um comando JSON ao MPV via IPC. Retorna True se bem-sucedido."""
    payload = (json.dumps({"command": command}) + "\n").encode("utf-8")
    try:
        if _IS_WINDOWS:
            # Named pipe: open() consegue escrever diretamente.
            with open(MPV_PIPE, "wb", buffering=0) as pipe:
                pipe.write(payload)
        else:
            # UNIX domain socket.
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.connect(MPV_PIPE)
                sock.sendall(payload)
            finally:
                sock.close()
        return True
    except Exception:
        return False


class PlayerManager:
    def __init__(self, config: dict):
        self.config = config
        self.playing = False
        self.status = "Aguardando buffer..."
        self._stop_event = threading.Event()
        self._mpv_process = None
        self._queued_segments: set = set()

    # ------------------------------------------------------------------ #
    #  Controle de delay (pode ser chamado de fora em tempo real)         #
    # ------------------------------------------------------------------ #

    def set_delay(self, seconds: int):
        """Altera o delay em tempo real (o efeito aparece nas próximas leituras)."""
        self.config["delay_seconds"] = max(10, seconds)

    def get_delay(self) -> int:
        return self.config["delay_seconds"]

    # ------------------------------------------------------------------ #
    #  Lógica de segmentos                                                 #
    # ------------------------------------------------------------------ #

    def _parse_segment_time(self, seg: Path) -> datetime | None:
        try:
            return datetime.strptime(seg.stem, "%Y%m%d_%H%M%S")
        except ValueError:
            return None

    def _get_ready_segments(self) -> list[Path]:
        """Retorna segmentos prontos para exibição (mais velhos que o delay)."""
        segments_dir = Path(self.config["segment_folder"])
        delay = timedelta(seconds=self.config["delay_seconds"])
        cutoff = datetime.now() - delay

        ready = []
        for seg in sorted(segments_dir.glob("*.ts")):
            seg_time = self._parse_segment_time(seg)
            if seg_time and seg_time <= cutoff:
                ready.append(seg)
        return ready

    def _buffer_progress(self) -> float:
        """Retorna 0.0–1.0 indicando quanto do buffer já está preenchido."""
        segments_dir = Path(self.config["segment_folder"])
        total_segments = len(list(segments_dir.glob("*.ts")))
        needed = self.config["delay_seconds"] / self.config["segment_duration"]
        return min(1.0, total_segments / needed) if needed > 0 else 0.0

    # ------------------------------------------------------------------ #
    #  MPV                                                                 #
    # ------------------------------------------------------------------ #

    def _build_mpv_cmd(self, first_segment: Path) -> list:
        monitor = self.config.get("mpv_fullscreen_monitor", 0)
        windowed = bool(self.config.get("windowed_mode", False))
        cmd = [
            bundled_binary("mpv"),
            f"--input-ipc-server={MPV_PIPE}",
            "--really-quiet",
            "--no-terminal",
            "--no-osc",
            "--no-osd-bar",
            "--keep-open=always",       # Não fecha ao acabar a playlist
            "--idle=yes",
            "--hr-seek=yes",
        ]
        if windowed:
            # Modo janela: útil para validar via acesso remoto (RustDesk, RDP),
            # que geralmente não captura bem janelas em fullscreen exclusivo.
            # Em produção com display físico, manter desligado.
            cmd += [
                "--no-fullscreen",
                "--geometry=1280x720",
                "--autofit=80%",
            ]
        else:
            cmd += [
                "--fullscreen",
                f"--screen={monitor}",
                f"--fs-screen={monitor}",
            ]
        cmd.append(str(first_segment))
        return cmd

    def _start_mpv(self, first_segment: Path):
        cmd = self._build_mpv_cmd(first_segment)
        self._mpv_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1.5)  # Aguarda o MPV criar o IPC

    def _queue_segment(self, seg: Path):
        """
        Adiciona segmento na fila do MPV.

        Usa `append-play` em vez de `append`: se o MPV já reproduziu tudo da
        playlist e está parado na última frame (por causa de `--keep-open`),
        `append` apenas empilha sem destravar — vídeo congela após o último
        segmento conhecido. `append-play` empilha E inicia a reprodução se
        estiver parado, garantindo continuidade quando novos segmentos
        chegam depois de uma pausa.
        """
        if seg in self._queued_segments:
            return
        if _send_mpv(["loadfile", str(seg), "append-play"]):
            self._queued_segments.add(seg)

    def _check_mpv_alive(self) -> bool:
        return self._mpv_process is not None and self._mpv_process.poll() is None

    # ------------------------------------------------------------------ #
    #  Loop principal                                                      #
    # ------------------------------------------------------------------ #

    def run(self):
        segments_dir = Path(self.config["segment_folder"])

        # --- Fase 1: aguarda buffer encher ---
        while not self._stop_event.is_set():
            progress = self._buffer_progress()
            pct = int(progress * 100)
            delay = self.config["delay_seconds"]
            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
            self.status = f"Buffer [{bar}] {pct}% ({delay}s)"

            ready = self._get_ready_segments()
            if len(ready) >= 2:
                break
            self._stop_event.wait(1)

        if self._stop_event.is_set():
            return

        # --- Fase 2: inicia o MPV com o primeiro segmento ---
        ready = self._get_ready_segments()
        if not ready:
            self.status = "Erro: nenhum segmento pronto"
            return

        first = ready[0]
        self._queued_segments.add(first)
        self._start_mpv(first)
        self.playing = True
        self.status = "Reproduzindo"

        # Enfileira os segmentos já prontos (além do primeiro)
        for seg in ready[1:]:
            self._queue_segment(seg)
            time.sleep(0.05)

        # --- Fase 3: alimenta o MPV continuamente ---
        while not self._stop_event.is_set():
            # Verifica se o MPV ainda está rodando
            if not self._check_mpv_alive():
                self.playing = False
                self.status = "MPV encerrado — reiniciando..."
                time.sleep(2)
                # Tenta reiniciar com o ponto atual
                ready = self._get_ready_segments()
                if ready:
                    # Encontra o último segmento já reproduzido
                    not_queued = [s for s in ready if s not in self._queued_segments]
                    start = not_queued[0] if not_queued else ready[-1]
                    self._queued_segments.add(start)
                    self._start_mpv(start)
                    self.playing = True
                    self.status = "Reproduzindo"
                continue

            # Enfileira novos segmentos prontos
            ready = self._get_ready_segments()
            for seg in ready:
                self._queue_segment(seg)

            delay = self.config["delay_seconds"]
            self.status = f"Reproduzindo  |  Delay: {delay}s ({delay//60}min {delay%60:02d}s)"
            self._stop_event.wait(1)

    def stop(self):
        self._stop_event.set()
        self.playing = False
        if self._mpv_process:
            try:
                self._mpv_process.terminate()
                self._mpv_process.wait(timeout=5)
            except Exception:
                self._mpv_process.kill()
