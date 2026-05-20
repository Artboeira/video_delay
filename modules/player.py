r"""
modules/player.py — Playback com delay usando MPV (malha fechada).

Aguarda o buffer de segmentos encher (delay configurado), inicia o MPV e o
mantém alimentado com os próximos segmentos via IPC.

A correção de delay é feita em **malha fechada**: a cada ciclo o player
pergunta ao MPV em que arquivo e em que posição ele está, calcula o delay
*real* (now − tempo de captura do frame exibido) e, se ele divergir do alvo
além da tolerância, salta o playhead para o ponto correto. Sem isso o delay
só cresce — cada gap entre segmentos e cada pausa por buffer seco vira atraso
permanente, e o delay configurado deixa de valer ao longo de horas.

Canal IPC:
  - Windows: named pipe  \\.\pipe\mpv-delay-system
  - macOS/Linux: UNIX domain socket em $TMPDIR/mpv-delay-system.sock

Toda chamada IPC roda numa thread efêmera com join(timeout): um MPV travado
nunca congela a thread do player.
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
from .logging_setup import log


_IS_WINDOWS = sys.platform == "win32"

# Teto de entradas mantidas na playlist do MPV. Sem isso a playlist cresce
# indefinidamente em sessões longas (cada .ts reproduzido fica nela). 40
# entradas ≈ 200s de playlist com segmentos de 5s — folgado vs qualquer delay.
MPV_PLAYLIST_CAP = 40

# Tolerância (s) entre o delay real e o alvo antes de corrigir o playhead.
# Abaixo disso não vale o glitch de um salto; acima, corrige.
DRIFT_TOLERANCE_SECONDS = 4.0

# Timeout (s) de cada chamada IPC ao MPV. Curto de propósito — o MPV responde
# em milissegundos quando saudável; se estourar é porque travou.
IPC_TIMEOUT = 2.0

# request_id fixo: cada chamada abre sua própria conexão, então não há colisão.
_IPC_REQUEST_ID = 1

# Caminho do canal IPC do MPV. No Windows usa named pipe; em Unix, socket UNIX.
# O MPV aceita ambos via --input-ipc-server=<caminho>.
if _IS_WINDOWS:
    MPV_PIPE = r"\\.\pipe\mpv-delay-system"
else:
    MPV_PIPE = str(Path(tempfile.gettempdir()) / "mpv-delay-system.sock")


# ────────────────────────────────────────────────────────────────────────── #
#  IPC com o MPV                                                              #
# ────────────────────────────────────────────────────────────────────────── #

def _read_reply(readline, max_lines: int = 60):
    """
    Lê linhas JSON do MPV até achar a resposta ao nosso request_id.

    O MPV intercala eventos (`{"event": ...}`) com respostas a comandos; só nos
    interessa a linha cujo `request_id` bate. Retorna (data, ok).
    """
    for _ in range(max_lines):
        try:
            line = readline()
        except (OSError, socket.timeout, ValueError):
            return None, False
        if not line:
            return None, False
        try:
            text = line.decode("utf-8") if isinstance(line, bytes) else line
            msg = json.loads(text)
        except (ValueError, TypeError):
            continue
        if isinstance(msg, dict) and msg.get("request_id") == _IPC_REQUEST_ID:
            if msg.get("error") == "success":
                return msg.get("data"), True
            return None, False
    return None, False


def _ipc_call(command: list, expect_reply: bool = False, timeout: float = IPC_TIMEOUT):
    """
    Envia um comando ao MPV via IPC. Retorna (data, ok).

    Toda a operação (connect + write + read) roda numa thread efêmera com
    join(timeout): um MPV travado bloqueia no máximo essa thread, nunca o
    chamador. `ok=False` indica falha de transporte, timeout ou erro do MPV.
    Com `expect_reply=False`, `data` é sempre None e `ok` só confirma a escrita.
    """
    box = {"data": None, "ok": False}

    def worker():
        try:
            obj = {"command": command}
            if expect_reply:
                obj["request_id"] = _IPC_REQUEST_ID
            payload = (json.dumps(obj) + "\n").encode("utf-8")

            if _IS_WINDOWS:
                # Named pipe. Modo r+b (duplex) só quando precisamos ler.
                mode = "r+b" if expect_reply else "wb"
                with open(MPV_PIPE, mode, buffering=(-1 if expect_reply else 0)) as pipe:
                    pipe.write(payload)
                    if expect_reply:
                        pipe.flush()
                        box["data"], box["ok"] = _read_reply(pipe.readline)
                    else:
                        box["ok"] = True
            else:
                # UNIX domain socket. settimeout é o backstop que faz o read
                # abortar caso o MPV pare de responder no meio.
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                try:
                    sock.connect(MPV_PIPE)
                    sock.sendall(payload)
                    if expect_reply:
                        reader = sock.makefile("rb")
                        box["data"], box["ok"] = _read_reply(reader.readline)
                    else:
                        box["ok"] = True
                finally:
                    sock.close()
        except Exception:
            pass

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout + 0.5)
    if t.is_alive():
        # MPV não respondeu a tempo. A thread é daemon e some sozinha.
        return None, False
    return box["data"], box["ok"]


def _send_mpv(command: list) -> bool:
    """Envia um comando JSON ao MPV (fire-and-forget). True se a escrita foi OK."""
    _data, ok = _ipc_call(command, expect_reply=False)
    return ok


def _query_mpv(prop: str):
    """Lê uma propriedade do MPV via IPC. Retorna (valor, ok)."""
    return _ipc_call(["get_property", prop], expect_reply=True)


class PlayerManager:
    def __init__(self, config: dict):
        self.config = config
        self.playing = False
        self.status = "Aguardando buffer..."
        # Delay real medido na última verificação (None até o MPV reportar).
        # Exposto no painel/status para o operador conferir o atraso de fato.
        self.measured_delay = None
        self._stop_event = threading.Event()
        self._mpv_process = None
        self._queued_segments: set = set()
        # Ciclos a pular após uma correção, para não medir o transiente do salto.
        self._correct_cooldown = 0

    # ------------------------------------------------------------------ #
    #  Controle de delay (pode ser chamado de fora em tempo real)         #
    # ------------------------------------------------------------------ #

    def set_delay(self, seconds: int):
        """Altera o delay em tempo real. A malha fechada ajusta o playhead."""
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

    def _prune_queued(self):
        """
        Remove do set de dedup os segmentos cujo arquivo já não existe.

        O set existe só para `_queue_segment` não reenfileirar o mesmo .ts.
        Podá-lo por *existência* (e não por idade) é o que garante que nunca
        reenfileiremos um segmento: assim que o cleaner apaga o arquivo, ele
        sai do set E deixa de aparecer em `_get_ready_segments` — os dois
        ficam consistentes. O set fica naturalmente limitado à retenção do
        cleaner (max_segment_age).
        """
        self._queued_segments = {s for s in self._queued_segments if s.exists()}

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
            "--keep-open=yes",          # Avança entre arquivos; pausa só no fim da playlist
            "--idle=yes",
            "--hr-seek=yes",            # Seek absoluto exato — usado na correção de drift
            # Pré-carrega o próximo item da playlist enquanto o atual ainda
            # toca. Sem isso o MPV abre cada .ts só ao terminar o anterior,
            # e esse gap (demux + decode do 1º frame) vira drift acumulado.
            "--prefetch-playlist=yes",
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

    def _wait_for_ipc(self, timeout: float = 10.0) -> bool:
        """
        Espera o canal IPC do MPV ficar pronto, sondando uma propriedade.

        Substitui o antigo `sleep(1.5)` fixo: numa máquina lenta o socket
        pode demorar mais que isso para existir, e os primeiros comandos se
        perderiam em silêncio. Retorna False se o MPV morreu ou estourou.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self._stop_event.is_set():
            if not self._check_mpv_alive():
                return False
            _data, ok = _query_mpv("idle-active")
            if ok:
                return True
            self._stop_event.wait(0.2)
        return False

    def _start_mpv(self, first_segment: Path):
        cmd = self._build_mpv_cmd(first_segment)
        self._mpv_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not self._wait_for_ipc():
            log.warning("IPC do MPV não respondeu a tempo — seguindo mesmo assim")

    def _queue_segment(self, seg: Path):
        """
        Adiciona segmento na fila do MPV.

        Com `--keep-open=yes`, MPV avança automaticamente entre arquivos da
        playlist e só pausa quando esgota o último — situação que acontece
        se o cleaner deletar segmentos mais rápido que o player consome ou
        se a captura travar. `append-play` empilha o novo segmento E
        destrava o MPV caso ele esteja pausado no fim da playlist.
        """
        if seg in self._queued_segments:
            return
        if _send_mpv(["loadfile", str(seg), "append-play"]):
            self._queued_segments.add(seg)

    def _check_mpv_alive(self) -> bool:
        return self._mpv_process is not None and self._mpv_process.poll() is None

    def _trim_playlist(self):
        """
        Mantém a playlist do MPV enxuta em sessões longas.

        Consulta o estado real do MPV (`playlist-count`, `playlist-pos`) em vez
        de inferir do set local — assim a poda nunca dessincroniza da playlist
        de fato. Remove a entrada de índice 0 (a mais antiga) apenas quando há
        excesso E o item em reprodução está pelo menos 2 posições à frente,
        garantindo que nunca removemos o que está tocando — inclusive depois
        de um salto da correção de drift, que pode mover o playhead para trás.
        """
        count, okc = _query_mpv("playlist-count")
        if not okc or not isinstance(count, int) or count <= MPV_PLAYLIST_CAP:
            return
        pos, okp = _query_mpv("playlist-pos")
        if not okp or not isinstance(pos, int) or pos < 2:
            return
        _send_mpv(["playlist-remove", 0])

    # ------------------------------------------------------------------ #
    #  Malha fechada: medição e correção de drift                          #
    # ------------------------------------------------------------------ #

    def _measure_delay(self) -> float | None:
        """
        Mede o delay real: now − (timestamp do segmento + posição dentro dele).

        Lê `path` antes e depois de `time-pos`; se o arquivo mudou no meio das
        leituras, a medida cruzaria uma fronteira de segmento (erro de ~5s) —
        nesse caso descarta e tenta no próximo ciclo. Retorna None se não der
        para medir com confiança.
        """
        p1, ok1 = _query_mpv("path")
        tpos, okt = _query_mpv("time-pos")
        p2, ok2 = _query_mpv("path")
        if not (ok1 and okt and ok2):
            return None
        if p1 is None or p2 is None or p1 != p2 or tpos is None:
            return None
        seg_time = self._parse_segment_time(Path(p1))
        if seg_time is None:
            return None
        content_time = seg_time + timedelta(seconds=float(tpos))
        return (datetime.now() - content_time).total_seconds()

    def _jump_to(self, index: int, offset: float) -> bool:
        """
        Move o playhead do MPV para o item `index` da playlist, posição `offset`.

        Para saltar entre segmentos, seta `playlist-pos` e espera o novo item
        carregar (sondando até `playlist-pos`/`time-pos` confirmarem) antes do
        seek — senão o seek correria antes do demuxer e seria ignorado. Quando
        o alvo é o próprio segmento em reprodução, vai direto ao seek (sem
        corrida: o arquivo já está carregado).
        """
        pos, ok = _query_mpv("playlist-pos")
        if not ok:
            return False
        if pos != index:
            if not _send_mpv(["set_property", "playlist-pos", index]):
                return False
            deadline = time.monotonic() + 3.0
            settled = False
            while time.monotonic() < deadline and not self._stop_event.is_set():
                pos2, okp = _query_mpv("playlist-pos")
                tpos, okt = _query_mpv("time-pos")
                if okp and pos2 == index and okt and tpos is not None:
                    settled = True
                    break
                self._stop_event.wait(0.15)
            if not settled:
                return False
        _send_mpv(["seek", round(max(0.0, offset), 3), "absolute"])
        return True

    def _correct_drift(self):
        """
        Núcleo da malha fechada: mede o delay real e, se divergir do alvo além
        da tolerância, salta o playhead para o ponto que corresponde ao alvo.

        Funciona nos dois sentidos: corrige o drift acumulado (delay grande
        demais → pula para frente) e também as mudanças de delay em runtime
        (delay aumentado pelo operador → volta para conteúdo mais antigo).
        """
        if self._correct_cooldown > 0:
            self._correct_cooldown -= 1
            return

        actual = self._measure_delay()
        if actual is None:
            return
        self.measured_delay = actual

        target = self.config["delay_seconds"]
        if abs(actual - target) <= DRIFT_TOLERANCE_SECONDS:
            return

        playlist, ok = _query_mpv("playlist")
        if not ok or not isinstance(playlist, list) or not playlist:
            return

        # Ponto de conteúdo que o playhead deveria estar exibindo agora.
        target_content = datetime.now() - timedelta(seconds=target)

        # Última entrada da playlist cujo início é <= target_content.
        target_index = None
        target_start = None
        for i, item in enumerate(playlist):
            fn = item.get("filename") if isinstance(item, dict) else None
            st = self._parse_segment_time(Path(fn)) if fn else None
            if st is None:
                continue
            if st <= target_content:
                target_index, target_start = i, st
            else:
                break

        if target_index is None:
            # Alvo é mais antigo que tudo na playlist (delay aumentado além do
            # buffer disponível) — vai para o item mais antigo que ainda temos.
            target_index = 0
            fn0 = playlist[0].get("filename") if isinstance(playlist[0], dict) else None
            target_start = self._parse_segment_time(Path(fn0)) if fn0 else None

        offset = 0.0
        if target_start is not None:
            offset = max(0.0, (target_content - target_start).total_seconds())

        if self._jump_to(target_index, offset):
            self._correct_cooldown = 2
            log.info(
                "Drift corrigido: delay real %.1fs -> alvo %ds "
                "(salto para playlist[%d] +%.1fs)",
                actual, target, target_index, offset,
            )

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

        # --- Fase 3: alimenta o MPV e mantém o delay na malha fechada ---
        while not self._stop_event.is_set():
            # Verifica se o MPV ainda está rodando
            if not self._check_mpv_alive():
                self.playing = False
                self.status = "MPV encerrado — reiniciando..."
                self._stop_event.wait(2)
                ready = self._get_ready_segments()
                if ready:
                    # Reinício limpo: zera o dedup e marca todos os segmentos
                    # já prontos como "enfileirados" para não reaparecerem fora
                    # de ordem. Começa no mais recente que ainda respeita o
                    # delay; a malha fechada ajusta o playhead em seguida.
                    self._queued_segments = set(ready)
                    self._start_mpv(ready[-1])
                    self.playing = True
                    self.status = "Reproduzindo"
                    self.measured_delay = None
                    self._correct_cooldown = 0
                continue

            # Enfileira novos segmentos prontos
            ready = self._get_ready_segments()
            for seg in ready:
                self._queue_segment(seg)

            # Poda a playlist do MPV e o set de dedup para não crescerem.
            self._trim_playlist()
            self._prune_queued()

            # Malha fechada: mede o delay real e corrige se divergir do alvo.
            self._correct_drift()

            delay = self.config["delay_seconds"]
            if self.measured_delay is not None:
                self.status = (
                    f"Reproduzindo  |  alvo {delay}s  |  "
                    f"real {self.measured_delay:.0f}s"
                )
            else:
                self.status = (
                    f"Reproduzindo  |  Delay: {delay}s "
                    f"({delay//60}min {delay%60:02d}s)"
                )
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
