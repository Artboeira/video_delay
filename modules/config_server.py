"""
modules/config_server.py — Servidor HTTP local para o painel de configuração.

Roda em thread daemon paralela aos managers e expõe duas coisas:

  • `/`, `/style.css`, `/app.js`, `/fonts/*`, `/assets/*`
    → arquivos estáticos do painel (pasta `webui/`)

  • `/api/config`   GET → estado atual do config dict
                    POST → mescla mutações; persiste em config.json;
                           propaga via PlayerManager.set_delay etc.
    `/api/status`   GET → snapshot vivo (running, status, buffer)
    `/api/monitors` GET → lista de monitores enumerados pelo SO
    `/api/shutdown` POST → sinaliza encerramento limpo

Por que stdlib?  O CLAUDE.md do projeto proíbe deps PyPI em runtime.
`http.server` resolve com folga para um painel local single-user.

Segurança: bind em 127.0.0.1 apenas. Sem auth — assume operador local.
"""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .monitors import list_monitors
from .capture_devices import list_capture_devices
from .paths import setup_flag_path
from .logging_setup import log


# Garante MIME types para fontes (alguns sistemas não trazem por padrão).
mimetypes.add_type("font/otf", ".otf")
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("image/svg+xml", ".svg")


def _resolve_webui_dir() -> Path:
    """
    Resolve a pasta `webui/` tanto em execução normal (rodando do source)
    quanto empacotada via PyInstaller (`sys._MEIPASS`).

    Em frozen tenta múltiplos caminhos porque a estrutura do bundle varia
    entre plataformas e versões do PyInstaller:
      • Mac onedir : Contents/Resources/webui  (via sys._MEIPASS)
      • Win onedir : <exe>/_internal/webui     (via sys._MEIPASS)
      • Win 5.x    : <exe>/webui               (legado)
    Retorna o primeiro que contém index.html. Se nenhum existir, retorna
    o primeiro candidato (para o erro aparecer no log do app, não na import).
    """
    if getattr(sys, "_MEIPASS", None):
        candidates = [
            Path(sys._MEIPASS) / "webui",
            Path(sys.executable).resolve().parent / "_internal" / "webui",
            Path(sys.executable).resolve().parent / "webui",
        ]
        for c in candidates:
            if (c / "index.html").is_file():
                return c
        return candidates[0]
    return Path(__file__).resolve().parent.parent / "webui"


WEBUI_DIR = _resolve_webui_dir()

# Campos válidos para mutação via POST /api/config. Qualquer outra chave é
# descartada — defesa contra payloads que tentariam injetar campos arbitrários.
_ALLOWED_FIELDS = {
    "delay_seconds": int,
    "capture_device": str,
    "test_mode": bool,
    "segment_duration": int,
    "max_segment_age_seconds": int,
    "mpv_fullscreen_monitor": int,
    "windowed_mode": bool,
}

# Folga mínima exigida entre max_segment_age_seconds e delay_seconds. Cobre o
# intervalo de 30s do loop do cleaner mais o jitter de captura — sem ela o
# cleaner pode apagar um segmento que o player ainda quer.
_MIN_AGE_MARGIN = 60


def _coerce(field: str, value):
    expected = _ALLOWED_FIELDS[field]
    if expected is bool:
        return bool(value)
    if expected is int:
        return int(value)
    if expected is str:
        return str(value)
    return value


# ──────────────────────────────────────────────────────────────────────
#  Handler
# ──────────────────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    # Atributos injetados pelo factory abaixo
    state: "ServerState"

    # Silencia logs do BaseHTTPServer (poluem o status do main.py)
    def log_message(self, fmt, *args):
        return

    # ─────────── helpers ───────────

    def _send_json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_static(self, rel_path: str):
        # Resolve via WEBUI_DIR e garante que o caminho final está dentro dela
        # (defesa contra path traversal).
        try:
            target = (WEBUI_DIR / rel_path).resolve()
            target.relative_to(WEBUI_DIR.resolve())
        except (ValueError, OSError) as e:
            log.warning("static path inválido: rel=%s base=%s err=%s", rel_path, WEBUI_DIR, e)
            self.send_error(404)
            return
        if not target.is_file():
            log.warning("static não encontrado: %s (base WEBUI_DIR=%s)", target, WEBUI_DIR)
            self.send_error(404)
            return
        ctype, _ = mimetypes.guess_type(str(target))
        ctype = ctype or "application/octet-stream"
        try:
            data = target.read_bytes()
        except OSError:
            self.send_error(500)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        # Cache leve — pode reverter depois de mudança CSS via hard refresh.
        self.send_header("Cache-Control", "public, max-age=60")
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    # ─────────── routes ───────────

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/":
            self._send_static("index.html")
            return

        if path == "/api/config":
            self._send_json(self.state.snapshot_config())
            return

        if path == "/api/status":
            self._send_json(self.state.snapshot_status())
            return

        if path == "/api/monitors":
            monitors = [m.to_dict() for m in list_monitors()]
            self._send_json(monitors)
            return

        if path == "/api/capture-devices":
            devices = [d.to_dict() for d in list_capture_devices()]
            self._send_json(devices)
            return

        if path == "/api/setup-status":
            # Setup é considerado completo se o flag existe E:
            #   - está em test_mode (placa não importa), OU
            #   - capture_device não é mais o placeholder
            placeholder = self.state.is_placeholder_device()
            test_mode = bool(self.state.config.get("test_mode"))
            complete = setup_flag_path().exists() and (test_mode or not placeholder)
            self._send_json({"complete": complete})
            return

        # Estático (style.css, app.js, fonts/*, assets/*)
        rel = path.lstrip("/")
        if not rel:
            self.send_error(404)
            return
        self._send_static(rel)

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/config":
            try:
                payload = self._read_json()
            except json.JSONDecodeError:
                self._send_json({"error": "invalid json"}, status=400)
                return
            try:
                updated = self.state.apply_config(payload)
            except ValueError as e:
                self._send_json({"error": str(e)}, status=400)
                return
            self._send_json(updated)
            return

        if path == "/api/shutdown":
            self.state.request_shutdown()
            self._send_json({"ok": True})
            return

        if path == "/api/setup-complete":
            try:
                payload = self._read_json()
            except json.JSONDecodeError:
                payload = {}
            try:
                self.state.mark_setup_complete(payload)
            except ValueError as e:
                self._send_json({"error": str(e)}, status=400)
                return
            self._send_json({"ok": True})
            return

        self.send_error(404)


# ──────────────────────────────────────────────────────────────────────
#  ServerState — adapter entre HTTP e os managers
# ──────────────────────────────────────────────────────────────────────

class ServerState:
    """
    Wrapper fino que dá ao handler acesso aos managers vivos e ao config dict
    compartilhado. O dict é mutado in-place (invariante do main.py); o player
    é avisado explicitamente em alterações de delay.
    """

    def __init__(self, config: dict, capture, player, cleaner,
                 config_path: Path, shutdown_event: threading.Event):
        self.config = config
        self.capture = capture
        self.player = player
        self.cleaner = cleaner
        self.config_path = config_path
        self.shutdown_event = shutdown_event
        self._lock = threading.Lock()

    # ── snapshots ─────────────────────────────────────────────

    def snapshot_config(self) -> dict:
        with self._lock:
            # Copia para evitar mutação acidental pelo cliente.
            return json.loads(json.dumps(self.config))

    def snapshot_status(self) -> dict:
        # Calcula progresso do buffer chamando o player (não bloqueia).
        try:
            buffer_progress = self.player._buffer_progress()
        except Exception:
            buffer_progress = 0.0
        return {
            "capture_running": bool(self.capture.running),
            "capture_error":   self.capture.error_message or "",
            "player_playing":  bool(self.player.playing),
            "player_status":   self.player.status,
            "buffer_progress": float(buffer_progress),
            "deleted_count":   int(self.cleaner.deleted_count),
            "delay_seconds":   int(self.player.get_delay()),
            "monitor":         int(self.config.get("mpv_fullscreen_monitor", 0)),
            "test_mode":       bool(self.config.get("test_mode", False)),
            "timestamp":       time.time(),
        }

    # ── mutação ───────────────────────────────────────────────

    def apply_config(self, payload: dict) -> dict:
        """
        Aplica mutações no config dict compartilhado e persiste em disco.

        Regras:
        - max_segment_age_seconds deve ser >= delay_seconds + _MIN_AGE_MARGIN
          (senão o cleaner apaga segmentos que o player ainda quer).
        - delay_seconds mínimo é 10 (clamp no PlayerManager mas validamos antes).
        - capture_device em modo de teste é irrelevante (mas aceito).
        - Mudança de qualquer campo fora de delay implica em reiniciar captura
          (FFmpeg precisa reler argumentos). Sinalizamos via capture.restart_requested.
        """
        clean = {}
        for k, v in payload.items():
            if k in _ALLOWED_FIELDS:
                clean[k] = _coerce(k, v)

        # video_quality é nested — tratado à parte para preservar shape.
        vq = payload.get("video_quality")
        if isinstance(vq, dict):
            preset = str(vq.get("preset", self.config["video_quality"]["preset"]))
            crf = int(vq.get("crf", self.config["video_quality"]["crf"]))
            if not (0 <= crf <= 51):
                raise ValueError("crf precisa estar entre 0 e 51")
            clean["video_quality"] = {"preset": preset, "crf": crf}

        # Validações cruzadas
        delay = clean.get("delay_seconds", self.config["delay_seconds"])
        if delay < 10:
            raise ValueError("delay_seconds mínimo é 10")
        max_age = clean.get("max_segment_age_seconds", self.config["max_segment_age_seconds"])
        if max_age < delay + _MIN_AGE_MARGIN:
            raise ValueError(
                f"max_segment_age_seconds precisa ser >= delay + {_MIN_AGE_MARGIN}s "
                f"(mínimo {delay + _MIN_AGE_MARGIN} para este delay)")

        # Aplica em memória e persiste
        with self._lock:
            # Detecta mudanças que exigem reinício da captura (FFmpeg).
            capture_affecting = {
                "capture_device", "test_mode", "segment_duration", "video_quality"
            }
            capture_needs_restart = any(
                k in clean and clean[k] != self.config.get(k)
                for k in capture_affecting
            )

            self.config.update(clean)
            self.player.set_delay(self.config["delay_seconds"])

            # Persistência atômica: escreve em .tmp e move.
            tmp = self.config_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.config, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.config_path)

            if capture_needs_restart:
                # CaptureManager.request_restart() é adicionado no capture.py.
                try:
                    self.capture.request_restart()
                except AttributeError:
                    pass  # fallback silencioso — só delay/monitor mudaram

            return json.loads(json.dumps(self.config))

    def request_shutdown(self):
        self.shutdown_event.set()

    # ── first-run wizard ──────────────────────────────────────

    def is_placeholder_device(self) -> bool:
        """True quando capture_device ainda é o valor default (não configurado)."""
        return self.config.get("capture_device") == "YOUR_CAPTURE_CARD_NAME"

    def mark_setup_complete(self, payload: dict | None = None):
        """
        Aceita opcionalmente um config inline (mesmo shape do POST /api/config)
        e aplica antes de marcar. Útil pro wizard fazer "save + finish" atômico.
        """
        if payload:
            self.apply_config(payload)
        setup_flag_path().parent.mkdir(parents=True, exist_ok=True)
        setup_flag_path().touch()


# ──────────────────────────────────────────────────────────────────────
#  Façade pública
# ──────────────────────────────────────────────────────────────────────

class ConfigServer:
    """
    Servidor HTTP daemon que serve o painel. Use `start()` antes das threads
    dos managers; `stop()` no encerramento.

    Porta default 8765. Se ocupada, tenta 8766…8774 antes de desistir.
    """

    DEFAULT_PORT = 8765
    PORT_RANGE = 10

    def __init__(self, state: ServerState, host: str = "127.0.0.1",
                 port: int | None = None):
        self.state = state
        self.host = host
        self.requested_port = port
        self.port: int | None = None
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/" if self.port else ""

    def _make_handler_class(self):
        state = self.state

        class Handler(_Handler):
            pass

        Handler.state = state
        return Handler

    def _bind(self) -> ThreadingHTTPServer:
        last_err = None
        candidates = (
            [self.requested_port] if self.requested_port
            else list(range(self.DEFAULT_PORT, self.DEFAULT_PORT + self.PORT_RANGE))
        )
        handler_cls = self._make_handler_class()
        for p in candidates:
            try:
                srv = ThreadingHTTPServer((self.host, p), handler_cls)
                self.port = p
                return srv
            except OSError as e:
                last_err = e
                continue
        raise RuntimeError(f"não foi possível abrir porta para o painel: {last_err}")

    def start(self):
        self._server = self._bind()
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="config-server",
        )
        self._thread.start()

    def stop(self):
        if self._server:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None
