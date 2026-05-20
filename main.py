"""
main.py — Video Delay System

Captura o sinal de uma placa de captura HDMI e reproduz
com um delay configurável em tela cheia.

Em execução do source (`python main.py`) o app se comporta como sempre:
banner ASCII, status line em tempo real, teclado capturado. Quando empacotado
via PyInstaller `--windowed`, todo output decorativo é suprimido e o painel
web vira a única UI — o app fica invisível até o browser abrir.

Controles durante a execução (no terminal, modo dev):
  P  →  abre o painel de configuração (Estúdio AB) no navegador
  +  →  aumenta o delay em 30 segundos
  -  →  diminui o delay em 30 segundos
  r  →  recarrega o config.json
  q  →  encerra o sistema

Requisitos (modo dev):
  - FFmpeg no PATH  (https://ffmpeg.org/download.html)
  - MPV no PATH     (https://mpv.io/installation/)
  - Python 3.11+    (apenas em execução source — no executável é embarcado)
"""

import json
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from modules import (
    CaptureManager, PlayerManager, CleanerManager,
    ConfigServer, ServerState,
)
from modules.paths import (
    config_path, segments_dir, ensure_user_data_dir,
    bundled_binary, is_frozen,
)
from modules.logging_setup import setup_logging, log, stdout_is_tty


# Teclado não-bloqueante: msvcrt no Windows; no macOS/Linux usamos termios.
# Sem termios (ex.: empacotado em modo --windowed sem TTY) caímos no fallback:
# o painel web é o único controle.
_HAS_KEYBOARD = False
_msvcrt = None
try:
    import msvcrt as _msvcrt  # type: ignore
    _HAS_KEYBOARD = True
except ImportError:
    try:
        import termios, tty, select  # noqa: F401
        _HAS_KEYBOARD = bool(sys.stdin and sys.stdin.isatty())
    except (ImportError, AttributeError):
        _HAS_KEYBOARD = False


STEP = 30  # Segundos por pressionamento de +/-

# Janela de portas para o painel — mesma do ConfigServer.PORT_RANGE.
# Usada pelo single-instance lock abaixo.
_PORT_BASE = 8765
_PORT_COUNT = 10


def detect_running_instance() -> str | None:
    """
    Se já existe outra instância do app rodando, devolve a URL do painel dela.
    Caso contrário devolve None.

    Heurística: tenta GET http://127.0.0.1:<porta>/api/status em cada porta
    da janela do painel; se a resposta contém a chave 'buffer_progress' é
    quase certo que é o nosso app. Timeout curto para não atrasar o boot.
    """
    for port in range(_PORT_BASE, _PORT_BASE + _PORT_COUNT):
        url = f"http://127.0.0.1:{port}"
        try:
            with urllib.request.urlopen(f"{url}/api/status", timeout=0.3) as r:
                body = r.read(2048).decode("utf-8", errors="replace")
                if "buffer_progress" in body:
                    return f"{url}/"
        except (urllib.error.URLError, OSError, TimeoutError):
            continue
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  Output helpers — TTY-only para banners/status, log() para eventos
# ─────────────────────────────────────────────────────────────────────────────

def tty(msg: str = "", *, end: str = "\n", flush: bool = False):
    """Escreve no terminal só quando há TTY. Em modo frozen é no-op."""
    if stdout_is_tty():
        try:
            sys.stdout.write(msg + end)
            if flush:
                sys.stdout.flush()
        except (OSError, AttributeError):
            pass


def clear_status_line():
    """Limpa a linha de status (\\r + espaços). Só faz sentido em TTY."""
    if stdout_is_tty():
        tty("\r" + " " * 140 + "\r", end="", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
#  Config
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "delay_seconds": 120,
    "segment_duration": 5,
    "capture_device": "YOUR_CAPTURE_CARD_NAME",
    "segment_folder": "segments",
    "max_segment_age_seconds": 240,
    "mpv_fullscreen_monitor": 0,
    "test_mode": False,
    "windowed_mode": False,
    "video_quality": {"preset": "ultrafast", "crf": 18},
}


def load_config() -> dict:
    """Lê config.json do user_data_dir. Sai com erro se não existir."""
    path = config_path()
    if not path.exists():
        log.error("config.json não encontrado em %s", path)
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def ensure_config_exists():
    """Cria um config padrão se ainda não existe. Bootstrap de primeira execução."""
    path = config_path()
    if path.exists():
        return
    ensure_user_data_dir()
    path.write_text(
        json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("config.json criado com defaults em %s", path)


def validate_config(config: dict) -> bool:
    """
    Retorna True se a config é válida para captura ativa.
    False indica que falta configurar a placa — caller deve mostrar o painel.
    """
    if config.get("test_mode"):
        return True
    if config.get("capture_device") == "YOUR_CAPTURE_CARD_NAME":
        log.warning("capture_device ainda é placeholder — abrir painel para configurar")
        # Banner só aparece em TTY; cliente empacotado já tem o wizard no browser.
        tty()
        tty("  ╔══════════════════════════════════════════════════╗")
        tty("  ║  Configure o dispositivo de captura pelo painel  ║")
        tty("  ║  ou rode em modo de teste (--test).              ║")
        tty("  ╚══════════════════════════════════════════════════╝")
        tty()
        return False
    return True


def check_dependencies() -> list[str]:
    """Retorna lista de binários ausentes (vazio se tudo OK)."""
    missing = []
    # bundled_binary devolve um caminho absoluto se empacotado, ou o `name` se
    # nada foi encontrado. Comparar com o próprio nome detecta ausência.
    if bundled_binary("ffmpeg") == "ffmpeg" and not shutil.which("ffmpeg"):
        missing.append("ffmpeg")
    if bundled_binary("mpv") == "mpv" and not shutil.which("mpv"):
        missing.append("mpv")
    return missing


# ─────────────────────────────────────────────────────────────────────────────
#  Display de status (TTY-only)
# ─────────────────────────────────────────────────────────────────────────────

def format_delay(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    return f"{m}min {s:02d}s"


def display_status(capture: CaptureManager, player: PlayerManager,
                   cleaner: CleanerManager, panel_url: str):
    """Renderiza a linha de status no terminal. No-op fora de TTY."""
    if not stdout_is_tty():
        return
    cap_icon = "●" if capture.running else "○"
    play_icon = "▶" if player.playing else "■"
    delay_str = format_delay(player.get_delay())
    cap_err = f"  {capture.error_message[:40]}" if capture.error_message else ""

    line = (
        f"{cap_icon} CAPTURA{cap_err}  |  "
        f"{play_icon} {player.status}  |  "
        f"limpos: {cleaner.deleted_count}  |  "
        f"delay: {delay_str}  |  [P] painel  [q] sair"
    )
    tty(f"\r{line[:140]:<140}", end="", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
#  Teclado cross-platform
# ─────────────────────────────────────────────────────────────────────────────

class _PosixKeyReader:
    """Lê tecla sem Enter via termios em modo cbreak. macOS / Linux."""
    def __init__(self):
        import termios, tty as _tty
        self.termios = termios
        self.tty = _tty
        self.fd = sys.stdin.fileno()
        self.saved = None

    def __enter__(self):
        self.saved = self.termios.tcgetattr(self.fd)
        self.tty.setcbreak(self.fd)
        return self

    def __exit__(self, *exc):
        if self.saved is not None:
            self.termios.tcsetattr(self.fd, self.termios.TCSADRAIN, self.saved)

    def poll(self) -> str | None:
        import select
        if select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.read(1)
        return None


def _make_key_reader():
    if _msvcrt is not None:
        class _Win:
            def __enter__(self): return self
            def __exit__(self, *exc): pass
            def poll(self):
                if _msvcrt.kbhit():
                    return _msvcrt.getwch()
                return None
        return _Win()
    if _HAS_KEYBOARD:
        return _PosixKeyReader()

    class _Null:
        def __enter__(self): return self
        def __exit__(self, *exc): pass
        def poll(self): return None
    return _Null()


# ─────────────────────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    # Single-instance: antes de tudo, ver se já tem app rodando. Se sim,
    # foca/abre o painel da instância existente e sai silenciosamente. Evita
    # subir dois ffmpegs gravando na mesma pasta (corromperia segments).
    existing = detect_running_instance()
    if existing is not None:
        # Não usar log() aqui — não chamamos setup_logging para não criar
        # handler novo num arquivo que a primeira instância já mantém aberto.
        try:
            webbrowser.open(existing)
        except Exception:
            pass
        return

    # Logging precisa estar pronto antes de QUALQUER outra coisa — protege
    # contra prints residuais e garante que erros no bootstrap sejam gravados.
    setup_logging()
    ensure_config_exists()
    config = load_config()

    if "--test" in sys.argv or "-t" in sys.argv:
        config["test_mode"] = True

    # Força segments para o user_data_dir, independente do que está no JSON.
    # Em modo dev isso resolve para o repo (compatível com o histórico); em
    # frozen resolve para ~/Library/Application Support/VideoDelay/segments.
    config["segment_folder"] = str(segments_dir())
    segments_dir().mkdir(parents=True, exist_ok=True)

    test_banner = "  [MODO DE TESTE]" if config.get("test_mode") else ""
    device_label = (
        "lavfi testsrc2 (sintético)" if config.get("test_mode")
        else config.get("capture_device", "—")
    )

    missing_deps = check_dependencies()

    # Banner — só em TTY (cliente leigo nunca vê)
    tty()
    tty("  ╔══════════════════════════════════════════════════╗")
    tty(f"  ║   VIDEO DELAY SYSTEM   ·   Estúdio AB{test_banner:<12}║")
    tty("  ╚══════════════════════════════════════════════════╝")
    tty()
    tty(f"  Dispositivo : {device_label}")
    tty(f"  Delay       : {format_delay(config['delay_seconds'])}")
    tty(f"  Segmentos   : {config['segment_duration']}s cada")
    tty(f"  Qualidade   : preset={config['video_quality']['preset']} / crf={config['video_quality']['crf']}")
    if missing_deps:
        tty()
        tty(f"  [AVISO] binário(s) ausente(s): {', '.join(missing_deps)}")
        tty(f"          Em macOS:  brew install ffmpeg mpv")
        tty(f"          Em Windows: baixar de https://ffmpeg.org e https://mpv.io")
    if not _HAS_KEYBOARD and stdout_is_tty():
        tty(f"  Teclado     : controles via painel web apenas (sem TTY)")
    tty()

    # Sempre logar metadados de boot — utiliza arquivo de log
    log.info("Boot — frozen=%s, test_mode=%s, delay=%ss, device=%s",
             is_frozen(), config.get("test_mode"), config["delay_seconds"], device_label)
    if missing_deps:
        log.warning("Binários ausentes no PATH: %s", missing_deps)

    # Managers
    capture = CaptureManager(config)
    player = PlayerManager(config)
    cleaner = CleanerManager(config)

    # Limpeza de boot: descarta segmentos de sessões anteriores para o player
    # nunca reproduzir "buffer falso". Síncrono — nada grava .ts ainda.
    removed = cleaner.purge_all()
    log.info("Boot: %d segmento(s) de sessao anterior removido(s)", removed)

    # Shutdown sinalizador compartilhado com o painel web
    shutdown_event = threading.Event()

    # Sobe servidor HTTP do painel
    state = ServerState(
        config=config,
        capture=capture, player=player, cleaner=cleaner,
        config_path=config_path(),
        shutdown_event=shutdown_event,
    )
    config_server = ConfigServer(state)
    config_server.start()
    panel_url = config_server.url
    log.info("Painel em %s", panel_url)

    tty(f"  Painel      : {panel_url}  (tecla P)")
    tty()

    # Em modo empacotado, abre o browser automaticamente (única forma de
    # o cliente leigo ver alguma coisa após o duplo-clique). Em dev deixa
    # o usuário decidir via tecla P para não atrapalhar workflow.
    if is_frozen():
        try:
            webbrowser.open(panel_url)
            log.info("Browser aberto automaticamente em %s", panel_url)
        except Exception as e:
            log.warning("Falha ao abrir browser automaticamente: %s", e)

    # Validação de captura
    if not validate_config(config):
        tty(f"  Abra o painel para configurar: {panel_url}")
        try:
            webbrowser.open(panel_url)
        except Exception:
            pass

    # Threads dos managers
    threads = [
        threading.Thread(target=capture.run, daemon=True, name="capture"),
        threading.Thread(target=player.run,  daemon=True, name="player"),
        threading.Thread(target=cleaner.run, daemon=True, name="cleaner"),
    ]
    for t in threads:
        t.start()

    hint = "  P: painel  ·  +/-: delay  ·  r: reload config  ·  q: sair"
    if not _HAS_KEYBOARD:
        hint = f"  Painel em {panel_url} — Ctrl+C encerra"
    tty(hint + "\n")

    # Loop principal
    try:
        with _make_key_reader() as reader:
            while not shutdown_event.is_set():
                display_status(capture, player, cleaner, panel_url)

                key = reader.poll()
                if key:
                    k = key.lower()
                    if k == 'q':
                        break
                    elif k == 'p':
                        clear_status_line()
                        tty(f"  Abrindo painel: {panel_url}")
                        log.info("Abrindo painel (tecla P)")
                        try:
                            webbrowser.open(panel_url)
                        except Exception as e:
                            log.warning("Falha ao abrir browser: %s", e)
                    elif k == '+' or k == '=':
                        # adjust_delay valida invariantes, sobe max_age se
                        # preciso, persiste e avisa o player. A malha fechada
                        # do player reposiciona o playhead em seguida.
                        try:
                            new_delay = state.adjust_delay(STEP)
                            log.info("Delay aumentado para %ss", new_delay)
                        except Exception as e:
                            log.warning("Falha ao aumentar delay: %s", e)
                    elif k == '-':
                        try:
                            new_delay = state.adjust_delay(-STEP)
                            log.info("Delay diminuído para %ss", new_delay)
                        except Exception as e:
                            log.warning("Falha ao diminuir delay: %s", e)
                    elif k == 'r':
                        try:
                            new_config = load_config()
                            config.update(new_config)
                            config["segment_folder"] = str(segments_dir())
                            player.set_delay(config["delay_seconds"])
                            clear_status_line()
                            tty("  Config recarregado.")
                            log.info("Config recarregado do disco")
                        except Exception as e:
                            clear_status_line()
                            tty(f"  Erro ao recarregar config: {e}")
                            log.exception("Erro ao recarregar config")

                time.sleep(0.25)

    except KeyboardInterrupt:
        log.info("Ctrl+C recebido")

    # Encerramento
    tty("\n\n  Encerrando...")
    log.info("Encerrando managers")
    config_server.stop()
    capture.stop()
    player.stop()
    cleaner.stop()
    # purge_all depois de capture/player pararem: FFmpeg e MPV já soltaram
    # os handles dos .ts, então a deleção não falha no Windows.
    removed = cleaner.purge_all()
    log.info("Shutdown: %d segmento(s) removido(s)", removed)
    tty("  Sistema encerrado.\n")
    log.info("Sistema encerrado.")


if __name__ == "__main__":
    main()
