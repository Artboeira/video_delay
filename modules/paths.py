"""
modules/paths.py — Resolução de caminhos para dados e binários, por plataforma.

Quando o app roda do source (`python main.py`), tudo fica relativo ao repo
(comportamento de desenvolvimento histórico). Quando empacotado via PyInstaller,
config/segments/logs migram para um diretório por usuário, garantindo que o
cliente clicando duplo a partir do Finder/Explorer (CWD imprevisível) sempre
encontre seus dados — e que uma reinstalação por drag-and-drop preserve a config.

  • macOS  → ~/Library/Application Support/VideoDelay/
  • Windows → %APPDATA%/VideoDelay/
  • Linux  → ~/.config/VideoDelay/

Também resolve `ffmpeg` e `mpv` empacotados ao lado do executável: o módulo
`bundled_binary()` devolve o caminho absoluto se o binário estiver embarcado,
caso contrário recai em `shutil.which` (modo dev).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


_APP_NAME = "VideoDelay"


def is_frozen() -> bool:
    """True quando rodando dentro de um bundle PyInstaller."""
    return getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS")


def _project_root() -> Path:
    """Raiz do repo em modo dev. Resolve subindo um nível de `modules/`."""
    return Path(__file__).resolve().parent.parent


def user_data_dir() -> Path:
    """
    Diretório onde gravamos config.json, segments/ e logs/.

    Em modo dev fica no próprio repo (conveniente para inspecionar e testar);
    em modo frozen vai para o local canônico do SO.
    """
    if not is_frozen():
        return _project_root()

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / _APP_NAME
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / _APP_NAME
        return Path.home() / "AppData" / "Roaming" / _APP_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / _APP_NAME


def ensure_user_data_dir() -> Path:
    """Cria o user_data_dir se ainda não existir e devolve o Path. Idempotente."""
    d = user_data_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / "logs").mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return user_data_dir() / "config.json"


def segments_dir() -> Path:
    return user_data_dir() / "segments"


def log_path() -> Path:
    return user_data_dir() / "logs" / "videodelay.log"


def setup_flag_path() -> Path:
    """Arquivo-flag que indica que o first-run wizard já foi concluído."""
    return user_data_dir() / ".setup_complete"


def _bundle_bin_dir() -> Path | None:
    """
    Pasta `bin/` ao lado do executável, quando empacotado.

    PyInstaller `--add-binary "ffmpeg:bin"` deposita o arquivo em
    `sys._MEIPASS/bin/ffmpeg` no modo onefile e na pasta do exe no modo onedir.
    Tentamos ambos e usamos o primeiro que existir.
    """
    candidates: list[Path] = []
    if getattr(sys, "_MEIPASS", None):
        candidates.append(Path(sys._MEIPASS) / "bin")
    if is_frozen():
        candidates.append(Path(sys.executable).resolve().parent / "bin")
        # macOS .app: o binário fica em Contents/MacOS/ e os recursos em Contents/Resources/
        candidates.append(Path(sys.executable).resolve().parent.parent / "Resources" / "bin")
    for c in candidates:
        if c.exists() and c.is_dir():
            return c
    return None


def _vendor_bin_dir() -> Path | None:
    """
    Em modo dev (não-frozen) o `bundled_binary` também tenta o vendor/<plat>/
    populado pelo `scripts/fetch_binaries.py`, para que o operador possa rodar
    `python main.py` usando os mesmos binários que serão empacotados.
    """
    if is_frozen():
        return None
    if sys.platform == "darwin":
        import platform as _plat
        target = "mac-arm64" if _plat.machine() == "arm64" else "mac-x86_64"
    elif sys.platform == "win32":
        target = "win-x64"
    else:
        return None
    candidate = _project_root() / "vendor" / target
    return candidate if candidate.is_dir() else None


def _resolve_mac_mpv(candidate_root: Path) -> Path | None:
    """No Mac, mpv vem como bundle .app — o binário fica em Contents/MacOS/."""
    app = candidate_root / "mpv.app"
    if app.is_dir():
        inner = app / "Contents" / "MacOS" / "mpv"
        if inner.exists():
            return inner
    return None


def bundled_binary(name: str) -> str:
    """
    Devolve o caminho do binário `name` (sem extensão), priorizando o que vem
    embarcado no app empacotado. Em modo dev, tenta o `vendor/` populado pelo
    fetch_binaries (útil para testar com os mesmos binários do bundle), e por
    fim cai em `shutil.which`.
    """
    ext = ".exe" if sys.platform == "win32" else ""

    for base in (_bundle_bin_dir(), _vendor_bin_dir()):
        if base is None:
            continue
        # Caso especial Mac: mpv vive em mpv.app/Contents/MacOS/mpv.
        if sys.platform == "darwin" and name == "mpv":
            inner = _resolve_mac_mpv(base)
            if inner is not None:
                return str(inner)
        candidate = base / f"{name}{ext}"
        if candidate.exists():
            return str(candidate)

    found = shutil.which(name)
    return found or name  # último recurso: confiar no PATH em runtime
