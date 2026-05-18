"""
scripts/fetch_binaries.py — Baixa ffmpeg + mpv estáticos para empacotar no app.

Por que esse script existe:
O PyInstaller embute Python + nosso código, mas não inclui FFmpeg nem MPV.
Para o cliente leigo abrir o .zip e clicar duplo sem instalar mais nada, os
binários precisam vir junto. Esse script baixa builds estáticos confiáveis,
valida formato e tamanho, e organiza em `vendor/<target>/{ffmpeg,mpv,...}`
para o `build.py` consumir via `--add-binary`.

Uso:
    python scripts/fetch_binaries.py                     # auto-detecta plataforma
    python scripts/fetch_binaries.py --target mac-arm64
    python scripts/fetch_binaries.py --target win-x64
    python scripts/fetch_binaries.py --target all
    python scripts/fetch_binaries.py --force             # re-baixa mesmo se já existe

Idempotente: skip se o binário esperado já está em vendor/<target>/. Use --force
para forçar redownload (ex: depois de uma versão nova lançar com bugfix).

Fontes (validadas em 2026-05):
  - ffmpeg Win:        https://www.gyan.dev/ffmpeg/builds/ — build "essentials"
  - ffmpeg Mac:        https://github.com/eko5624/mpv-mac/releases/latest — arm64/x86_64
  - mpv Win:           https://github.com/shinchiro/mpv-winbuild-cmake/releases/latest
  - mpv Mac:           https://github.com/eko5624/mpv-mac/releases/latest — arm64/x86_64

Anti-tampering: validação mínima de tamanho + extensão. Para builds reproduzíveis
em produção, gerar um vendor/lockfile.json com SHA-256 dos artefatos após uma
execução conhecida-boa, e o script vai validar contra ele em execuções futuras.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import re
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
LOCKFILE = VENDOR / "lockfile.json"


# ──────────────────────────────────────────────────────────────────────
#  Definição de targets
# ──────────────────────────────────────────────────────────────────────

class Target:
    """Descreve uma combinação (sistema, arquitetura) e como buscar os binários."""

    def __init__(self, name: str, resolvers: dict[str, "BinaryResolver"]):
        self.name = name
        self.resolvers = resolvers


class BinaryResolver:
    """Resolve URL final, faz download e extrai o binário esperado.

    Dois modos de extração:
      - `binary` (default): extrai o membro `archive_member` como arquivo único
        e copia siblings (.dylib, .dll, etc.) do mesmo diretório lógico.
        Resultado: vendor/<target>/<output_name>
      - `app_bundle`: extrai uma árvore inteira a partir do prefixo
        `archive_member` (deve terminar com /). Preserva subdiretórios.
        Resultado: vendor/<target>/<output_name>/  (uma pasta)
    """

    def __init__(
        self,
        url_resolver: Callable[[], str],
        archive_member: str | re.Pattern,
        output_name: str,
        min_size_mb: int,
        mode: str = "binary",
    ):
        self.url_resolver = url_resolver
        self.archive_member = archive_member
        self.output_name = output_name
        self.min_size_mb = min_size_mb
        self.mode = mode


# ──────────────────────────────────────────────────────────────────────
#  URL resolvers
# ──────────────────────────────────────────────────────────────────────

def _gyan_ffmpeg_win_url() -> str:
    """URL fixo, redireciona para a versão atual."""
    return "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def _github_release_asset(repo: str, pattern: re.Pattern) -> str:
    """Resolve o URL de um asset cujo nome bate o regex.

    Estratégia: tenta `releases/latest` primeiro; se não houver match, percorre
    as releases mais recentes (até 5 no total) procurando a primeira que tenha
    um asset compatível. Necessário porque alguns repos (eko5624/mpv-mac) às
    vezes publicam uma release com builds incompletos (ex.: só x86_64 sem
    arm64) — a release anterior tinha tudo.

    Usa GITHUB_TOKEN do env se presente — necessário em CI porque o runner do
    GitHub Actions tem IP compartilhado e o rate limit anônimo (60 req/h) zera
    rápido. Com token autenticado o limite é 1000 req/h.
    """
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    def _match_in(release: dict) -> str | None:
        for asset in release.get("assets", []):
            if pattern.search(asset["name"]):
                return asset["browser_download_url"]
        return None

    # 1) Tenta a release marcada como "latest" pelo GitHub.
    api_latest = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(api_latest, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        latest = json.loads(r.read())
    url = _match_in(latest)
    if url:
        return url

    # 2) Fallback: percorre as 5 releases mais recentes (incluindo pré-releases).
    api_all = f"https://api.github.com/repos/{repo}/releases?per_page=5"
    req = urllib.request.Request(api_all, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        releases = json.loads(r.read())
    for release in releases:
        url = _match_in(release)
        if url:
            print(f"  [fallback] usando release {release.get('tag_name')} de {repo} "
                  f"(latest não tem asset com padrão {pattern.pattern})")
            return url

    raise RuntimeError(f"Nenhum asset em {repo} bate o padrão {pattern.pattern} "
                       f"(checadas latest + 5 releases anteriores)")


def _shinchiro_mpv_win() -> str:
    return _github_release_asset(
        "shinchiro/mpv-winbuild-cmake",
        re.compile(r"^mpv-x86_64-\d+-git-[a-f0-9]+\.7z$"),
    )


def _eko_mpv_mac_arm64() -> str:
    return _github_release_asset(
        "eko5624/mpv-mac",
        re.compile(r"^mpv-arm64-git-[a-f0-9]+\.zip$"),
    )


def _eko_mpv_mac_x86_64() -> str:
    return _github_release_asset(
        "eko5624/mpv-mac",
        re.compile(r"^mpv-x86_64-git-[a-f0-9]+\.zip$"),
    )


def _eko_ffmpeg_mac_arm64() -> str:
    return _github_release_asset(
        "eko5624/mpv-mac",
        re.compile(r"^ffmpeg-arm64-[a-f0-9]+\.zip$"),
    )


def _eko_ffmpeg_mac_x86_64() -> str:
    return _github_release_asset(
        "eko5624/mpv-mac",
        re.compile(r"^ffmpeg-x86_64-[a-f0-9]+\.zip$"),
    )


# ──────────────────────────────────────────────────────────────────────
#  Targets
# ──────────────────────────────────────────────────────────────────────

TARGETS: dict[str, Target] = {
    "mac-arm64": Target("mac-arm64", {
        "ffmpeg": BinaryResolver(
            url_resolver=_eko_ffmpeg_mac_arm64,
            archive_member=re.compile(r"(^|/)ffmpeg$"),
            output_name="ffmpeg",
            min_size_mb=5,
        ),
        # mpv no Mac vem como bundle .app com dylibs relativas (libluajit em
        # `lib/`, libMoltenVK em `../Frameworks/`). Preservar a árvore inteira
        # é a única forma de manter o @executable_path funcionando.
        "mpv": BinaryResolver(
            url_resolver=_eko_mpv_mac_arm64,
            archive_member="mpv/mpv.app/",
            output_name="mpv.app",
            min_size_mb=80,  # mpv.app inteiro ≈ 100MB
            mode="app_bundle",
        ),
    }),
    "mac-x86_64": Target("mac-x86_64", {
        "ffmpeg": BinaryResolver(
            url_resolver=_eko_ffmpeg_mac_x86_64,
            archive_member=re.compile(r"(^|/)ffmpeg$"),
            output_name="ffmpeg",
            min_size_mb=5,
        ),
        "mpv": BinaryResolver(
            url_resolver=_eko_mpv_mac_x86_64,
            archive_member="mpv/mpv.app/",
            output_name="mpv.app",
            min_size_mb=80,
            mode="app_bundle",
        ),
    }),
    "win-x64": Target("win-x64", {
        "ffmpeg": BinaryResolver(
            url_resolver=_gyan_ffmpeg_win_url,
            archive_member=re.compile(r"bin/ffmpeg\.exe$"),
            output_name="ffmpeg.exe",
            min_size_mb=80,  # gyan essentials ~100MB exe
        ),
        "mpv": BinaryResolver(
            url_resolver=_shinchiro_mpv_win,
            archive_member=re.compile(r"^mpv\.exe$"),
            output_name="mpv.exe",
            min_size_mb=20,
        ),
    }),
}


# ──────────────────────────────────────────────────────────────────────
#  Download + extract
# ──────────────────────────────────────────────────────────────────────

def detect_target() -> str:
    if sys.platform == "darwin":
        return "mac-arm64" if platform.machine() == "arm64" else "mac-x86_64"
    if sys.platform == "win32":
        return "win-x64"
    raise SystemExit(f"Plataforma não suportada: {sys.platform}")


def _stream_download(url: str, dest: Path):
    """Baixa com progresso simples no terminal (MB)."""
    print(f"  -> baixando {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "fetch_binaries/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        total = int(r.headers.get("Content-Length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            while True:
                chunk = r.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total * 100
                    print(f"\r    {downloaded//1024//1024:>4d}MB / {total//1024//1024}MB  ({pct:5.1f}%)",
                          end="", flush=True)
        print()


def _tree_size_mb(path: Path) -> int:
    """Tamanho em MB de arquivo ou diretório (recursivo)."""
    if path.is_file():
        return path.stat().st_size // 1024 // 1024
    if path.is_dir():
        total = 0
        for root, _, files in os.walk(path):
            for f in files:
                try:
                    total += (Path(root) / f).stat().st_size
                except OSError:
                    pass
        return total // 1024 // 1024
    return 0


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(64 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _extract_member(archive: Path, member_pattern, dest_dir: Path,
                    *, mode: str = "binary", output_name: str | None = None) -> Path:
    """
    Modo `binary`: extrai um único membro + siblings flat. Devolve o arquivo.
    Modo `app_bundle`: extrai toda a árvore sob `member_pattern` (que deve ser
    uma string com prefixo terminando em /). Devolve o diretório raiz.
    """
    if archive.suffix.lower() == ".zip":
        if mode == "app_bundle":
            return _extract_tree_from_zip(archive, member_pattern, dest_dir, output_name)
        return _extract_from_zip(archive, member_pattern, dest_dir)
    if archive.suffix.lower() == ".7z":
        if mode == "app_bundle":
            raise RuntimeError("app_bundle a partir de .7z ainda não implementado")
        return _extract_from_7z(archive, member_pattern, dest_dir)
    raise RuntimeError(f"Tipo de arquivo não suportado: {archive.suffix}")


def _extract_tree_from_zip(archive: Path, prefix: str, dest_dir: Path,
                           output_name: str | None) -> Path:
    """
    Extrai todos os arquivos do zip cujo nome começa com `prefix`, preservando
    a estrutura relativa, dentro de `dest_dir/<output_name>/`. Útil para
    bundles .app onde @executable_path depende de subdiretórios.
    """
    if not isinstance(prefix, str) or not prefix.endswith("/"):
        raise ValueError("app_bundle requer prefix string terminando em '/'")
    if not output_name:
        raise ValueError("app_bundle requer output_name explícito")

    root = dest_dir / output_name
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    extracted_any = False
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            if not info.filename.startswith(prefix):
                continue
            rel = info.filename[len(prefix):]
            if not rel:
                continue
            target = root / rel
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            # Preserva permissão de execução de binários (zip carrega no
            # external_attr os bits Unix no high half).
            mode = info.external_attr >> 16
            if mode:
                target.chmod(mode & 0o7777)
            extracted_any = True
    if not extracted_any:
        raise RuntimeError(f"Prefixo {prefix} não encontrado em {archive.name}")
    return root


def _matches(name: str, pattern) -> bool:
    if isinstance(pattern, re.Pattern):
        return bool(pattern.search(name))
    return name == pattern or name.endswith("/" + pattern)


def _extract_from_zip(archive: Path, member_pattern, dest_dir: Path) -> Path:
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            if _matches(info.filename, member_pattern):
                out_path = dest_dir / Path(info.filename).name
                with z.open(info) as src, open(out_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                out_path.chmod(0o755)
                # Também extrai .dylib/.dll/.so vizinhos (libs de runtime).
                # Estratégia: extrai todo o conteúdo do mesmo "diretório lógico"
                # do membro encontrado.
                base = "/".join(info.filename.split("/")[:-1])
                if base:
                    for other in z.infolist():
                        if other.is_dir() or other.filename == info.filename:
                            continue
                        if other.filename.startswith(base + "/"):
                            tail = other.filename[len(base) + 1:]
                            if "/" in tail:
                                continue  # subdir, ignora por enquanto
                            out = dest_dir / tail
                            with z.open(other) as s, open(out, "wb") as d:
                                shutil.copyfileobj(s, d)
                return out_path
    raise RuntimeError(f"Membro {member_pattern} não encontrado em {archive.name}")


def _find_7z_cli() -> str | None:
    """Localiza o binário `7z` (CLI). Procura no PATH e nos locais padrão do Windows."""
    found = shutil.which("7z") or shutil.which("7za")
    if found:
        return found
    # GitHub Actions windows-2022 traz 7-Zip pré-instalado mas nem sempre no PATH
    for candidate in (
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    ):
        if Path(candidate).exists():
            return candidate
    return None


def _extract_from_7z(archive: Path, member_pattern, dest_dir: Path) -> Path:
    """
    Extrai .7z preferindo a CLI `7z` (suporta todos os filtros, incluindo BCJ2
    usado por builds modernos do mpv para Windows). Cai em py7zr só se a CLI
    não estiver disponível — py7zr não implementa BCJ2 e quebra em vários
    artefatos do shinchiro/mpv-winbuild-cmake.
    """
    import subprocess

    cli = _find_7z_cli()
    if cli is not None:
        with tempfile.TemporaryDirectory() as td:
            subprocess.check_call([cli, "x", "-y", f"-o{td}", str(archive)],
                                  stdout=subprocess.DEVNULL)
            for root, _, files in os.walk(td):
                for f in files:
                    rel = os.path.relpath(os.path.join(root, f), td)
                    if _matches(rel.replace("\\", "/"), member_pattern):
                        src = Path(root) / f
                        dst = dest_dir / src.name
                        shutil.move(str(src), str(dst))
                        try:
                            dst.chmod(0o755)
                        except OSError:
                            pass  # Windows ignora chmod
                        return dst
        raise RuntimeError(f"Membro {member_pattern} não encontrado em {archive.name}")

    # Fallback py7zr — funciona para 7z sem filtros exóticos
    try:
        import py7zr  # type: ignore
    except ImportError:
        raise RuntimeError(
            "Para extrair .7z é preciso ter `7z` no PATH "
            "(choco install 7zip / brew install p7zip) ou `pip install py7zr`."
        )
    with py7zr.SevenZipFile(archive, mode="r") as z:
        names = z.getnames()
        for n in names:
            if _matches(n, member_pattern):
                z.extract(path=str(dest_dir), targets=[n])
                src = dest_dir / n
                dst = dest_dir / Path(n).name
                if src != dst:
                    shutil.move(str(src), str(dst))
                try:
                    dst.chmod(0o755)
                except OSError:
                    pass
                return dst
        raise RuntimeError(f"Membro {member_pattern} não encontrado em {archive.name}")


# ──────────────────────────────────────────────────────────────────────
#  Lockfile
# ──────────────────────────────────────────────────────────────────────

def _load_lock() -> dict:
    if LOCKFILE.exists():
        return json.loads(LOCKFILE.read_text())
    return {}


def _save_lock(data: dict):
    VENDOR.mkdir(parents=True, exist_ok=True)
    LOCKFILE.write_text(json.dumps(data, indent=2, sort_keys=True))


# ──────────────────────────────────────────────────────────────────────
#  Pipeline
# ──────────────────────────────────────────────────────────────────────

def fetch_target(target_name: str, *, force: bool = False, pin: bool = False):
    target = TARGETS[target_name]
    out_dir = VENDOR / target_name
    out_dir.mkdir(parents=True, exist_ok=True)

    lock = _load_lock()
    target_lock = lock.setdefault(target_name, {})

    for bin_name, resolver in target.resolvers.items():
        final = out_dir / resolver.output_name

        if final.exists() and not force:
            size_mb = _tree_size_mb(final)
            if size_mb >= resolver.min_size_mb:
                print(f"  [OK] {target_name}/{bin_name} já presente ({size_mb}MB)")
                continue
            print(f"  [!] {target_name}/{bin_name} pequeno demais ({size_mb}MB) — refazendo")

        print(f"[{target_name}/{bin_name}] resolvendo URL...")
        url = resolver.url_resolver()
        print(f"[{target_name}/{bin_name}] URL: {url}")

        with tempfile.TemporaryDirectory() as td:
            tmp_dir = Path(td)
            archive_name = url.split("/")[-1]
            archive_path = tmp_dir / archive_name
            _stream_download(url, archive_path)

            archive_size_mb = archive_path.stat().st_size // 1024 // 1024
            print(f"[{target_name}/{bin_name}] download OK ({archive_size_mb}MB)")

            extracted = _extract_member(
                archive_path,
                resolver.archive_member,
                out_dir,
                mode=resolver.mode,
                output_name=resolver.output_name,
            )
            extracted_size_mb = _tree_size_mb(extracted)
            print(f"[{target_name}/{bin_name}] extraído para {extracted} ({extracted_size_mb}MB)")

            if extracted_size_mb < resolver.min_size_mb:
                raise RuntimeError(
                    f"Binário extraído suspeito de incompleto: "
                    f"{extracted_size_mb}MB < min {resolver.min_size_mb}MB"
                )

        if pin and resolver.mode == "binary":
            target_lock[bin_name] = {
                "sha256": _sha256(final),
                "url": url,
            }

    if pin:
        _save_lock(lock)
        print(f"  -> lockfile gravado em {LOCKFILE}")


def main():
    parser = argparse.ArgumentParser(description="Fetch ffmpeg + mpv para o bundle.")
    parser.add_argument("--target", choices=list(TARGETS.keys()) + ["all", "auto"],
                        default="auto", help="plataforma alvo (default: auto-detecta)")
    parser.add_argument("--force", action="store_true",
                        help="re-baixa mesmo se já presente")
    parser.add_argument("--pin", action="store_true",
                        help="grava SHA-256 no lockfile (para builds reproduzíveis)")
    args = parser.parse_args()

    if args.target == "auto":
        targets = [detect_target()]
    elif args.target == "all":
        targets = list(TARGETS.keys())
    else:
        targets = [args.target]

    print(f"Targets: {', '.join(targets)}\n")
    for t in targets:
        fetch_target(t, force=args.force, pin=args.pin)

    print(f"\nFeito. Binários em {VENDOR}/")


if __name__ == "__main__":
    main()
