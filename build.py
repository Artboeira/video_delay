"""
build.py — Empacota o Video Delay System em um app standalone via PyInstaller.

Saída por plataforma:
  • macOS  → dist/VideoDelay.app/  +  dist/VideoDelay-mac.zip (com INSTALL.txt)
  • Windows → dist/VideoDelay/      +  dist/VideoDelay-win.zip (com INSTALL.txt)

O bundle contém:
  • Python + stdlib + nosso código (PyInstaller --onedir)
  • Pasta webui/ (HTML/CSS/JS/fontes) via --add-data
  • ffmpeg + mpv estáticos via --add-binary / --add-data (extraídos de vendor/)

Uso:
    python build.py                 # detecta plataforma, builda
    python build.py --clean         # apaga build/, dist/, .spec antes
    python build.py --console       # mantém terminal visível (debug)
    python build.py --skip-zip      # não cria o .zip de distribuição
    python build.py --skip-fetch    # não invoca fetch_binaries (assume vendor pronto)

Pré-requisito (build-time apenas): `pip install pyinstaller`. PyInstaller é a única
dep PyPI permitida e só roda neste script — runtime do app continua stdlib only.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
APP_NAME = "VideoDelay"
BUNDLE_ID = "io.estudioab.videodelay"


# ──────────────────────────────────────────────────────────────────────
#  Detecção de plataforma + targets do vendor/
# ──────────────────────────────────────────────────────────────────────

def detect_target() -> str:
    if sys.platform == "darwin":
        return "mac-arm64" if platform.machine() == "arm64" else "mac-x86_64"
    if sys.platform == "win32":
        return "win-x64"
    raise SystemExit(f"Plataforma não suportada: {sys.platform}")


def vendor_dir(target: str) -> Path:
    return ROOT / "vendor" / target


def have_pyinstaller() -> bool:
    try:
        __import__("PyInstaller")
        return True
    except ImportError:
        return False


def have_vendor(target: str) -> bool:
    d = vendor_dir(target)
    if not d.is_dir():
        return False
    if sys.platform == "darwin":
        return (d / "ffmpeg").exists() and (d / "mpv.app").is_dir()
    if sys.platform == "win32":
        return (d / "ffmpeg.exe").exists() and (d / "mpv.exe").exists()
    return False


def install_pyinstaller():
    print("→ Instalando PyInstaller (build-time only)...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pyinstaller"])


def fetch_vendor(target: str):
    print(f"→ Baixando ffmpeg + mpv para {target} (vendor/{target}/)...")
    subprocess.check_call(
        [sys.executable, str(ROOT / "scripts" / "fetch_binaries.py"), "--target", target],
        cwd=ROOT,
    )


def maybe_generate_icons():
    """Tenta gerar icons se faltarem. Silenciosa em falhas — ícones são opcionais."""
    icns = ROOT / "webui" / "assets" / "symbol.icns"
    ico = ROOT / "webui" / "assets" / "symbol.ico"
    if icns.exists() and ico.exists():
        return
    try:
        subprocess.check_call(
            [sys.executable, str(ROOT / "scripts" / "generate_icons.py")],
            cwd=ROOT,
        )
    except subprocess.CalledProcessError:
        print("  ⚠ Geração de ícones falhou — build seguirá sem ícone customizado.")


def clean():
    for p in ("build", "dist", f"{APP_NAME}.spec"):
        path = ROOT / p
        if path.is_dir():
            shutil.rmtree(path)
        elif path.is_file():
            path.unlink()
    print("→ Limpeza concluída.")


# ──────────────────────────────────────────────────────────────────────
#  Montagem do comando PyInstaller
# ──────────────────────────────────────────────────────────────────────

def _add_data_flag(src: str, dst: str) -> list[str]:
    """PyInstaller usa ';' no Windows e ':' nos demais para separar src e dst."""
    sep = ";" if platform.system() == "Windows" else ":"
    return ["--add-data", f"{src}{sep}{dst}"]


def _add_binary_flag(src: str, dst: str) -> list[str]:
    sep = ";" if platform.system() == "Windows" else ":"
    return ["--add-binary", f"{src}{sep}{dst}"]


def build_command(target: str, args) -> list[str]:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--onedir",            # bundle de pasta (boot mais rápido que --onefile)
        "--clean",
        "--noconfirm",
        "--noupx",             # UPX pode quebrar ffmpeg/mpv estáticos
    ]
    if not args.console:
        cmd.append("--windowed")

    # webui — pasta inteira (HTML/CSS/JS/fontes/assets)
    cmd += _add_data_flag("webui", "webui")

    # Binários — diferem por plataforma
    vdir = vendor_dir(target)
    if sys.platform == "darwin":
        # ffmpeg vai como --add-binary (PyInstaller assina/relinka)
        cmd += _add_binary_flag(str(vdir / "ffmpeg"), "bin")
        # mpv.app inteiro vai como --add-data (preserva a árvore)
        cmd += _add_data_flag(str(vdir / "mpv.app"), "bin/mpv.app")
        cmd += ["--osx-bundle-identifier", BUNDLE_ID]
        # Entitlements para AVFoundation funcionar (câmera + capture cards)
        entitlements = ROOT / "entitlements.plist"
        if entitlements.exists():
            cmd += ["--osx-entitlements-file", str(entitlements)]
        icon = ROOT / "webui" / "assets" / "symbol.icns"
        if icon.exists():
            cmd += ["--icon", str(icon)]
    elif sys.platform == "win32":
        cmd += _add_binary_flag(str(vdir / "ffmpeg.exe"), "bin")
        cmd += _add_binary_flag(str(vdir / "mpv.exe"), "bin")
        icon = ROOT / "webui" / "assets" / "symbol.ico"
        if icon.exists():
            cmd += ["--icon", str(icon)]

    # Hidden imports — módulos importados dinamicamente que PyInstaller pode perder
    for m in [
        "modules.capture", "modules.player", "modules.cleaner",
        "modules.config_server", "modules.monitors",
        "modules.paths", "modules.logging_setup", "modules.capture_devices",
    ]:
        cmd += ["--hidden-import", m]

    cmd.append("main.py")
    return cmd


def patch_info_plist():
    """
    Insere NSCameraUsageDescription no Info.plist gerado pelo PyInstaller.
    Sem essa string, o macOS bloqueia silenciosamente o acesso à câmera/placa.
    """
    if sys.platform != "darwin":
        return
    plist_path = ROOT / "dist" / f"{APP_NAME}.app" / "Contents" / "Info.plist"
    if not plist_path.is_file():
        return
    content = plist_path.read_text(encoding="utf-8")
    if "NSCameraUsageDescription" in content:
        return  # já existe
    injection = (
        "\t<key>NSCameraUsageDescription</key>\n"
        "\t<string>Captura o sinal de vídeo HDMI da sua placa para o efeito de delay.</string>\n"
        "\t<key>LSMinimumSystemVersion</key>\n"
        "\t<string>11.0</string>\n"
    )
    # Injeta antes do </dict> de fechamento principal (último antes de </plist>)
    new_content = content.replace("</dict>\n</plist>", injection + "</dict>\n</plist>")
    plist_path.write_text(new_content, encoding="utf-8")
    print("→ Info.plist patched (NSCameraUsageDescription, LSMinimumSystemVersion)")


# ──────────────────────────────────────────────────────────────────────
#  Pós-processamento: zip de distribuição
# ──────────────────────────────────────────────────────────────────────

def write_install_txt() -> Path:
    """Gera INSTALL.txt no dist/ para incluir no zip."""
    path = ROOT / "dist" / "INSTALL.txt"
    path.write_text(
        "═══════════════════════════════════════════════════════\n"
        "  VIDEO DELAY · ESTÚDIO AB · INSTRUÇÕES DE INSTALAÇÃO\n"
        "═══════════════════════════════════════════════════════\n"
        "\n"
        "  MAC OS\n"
        "  ─────────────────────────────────────────────\n"
        "  1. Arraste VideoDelay.app para a pasta Aplicativos.\n"
        "  2. Na primeira abertura: BOTÃO DIREITO no ícone,\n"
        "     escolha \"Abrir\".\n"
        "  3. Se aparecer \"desenvolvedor não identificado\",\n"
        "     clique em \"Abrir\" outra vez. Nas próximas vezes\n"
        "     basta clique duplo normalmente.\n"
        "\n"
        "  WINDOWS\n"
        "  ─────────────────────────────────────────────\n"
        "  1. Extraia toda a pasta VideoDelay para algum lugar\n"
        "     que faça sentido (Documentos, Área de Trabalho).\n"
        "  2. Clique duplo em VideoDelay.exe.\n"
        "  3. Se aparecer aviso do SmartScreen, clique em\n"
        "     \"Mais informações\" e depois \"Executar mesmo assim\".\n"
        "\n"
        "  PRIMEIRA EXECUÇÃO\n"
        "  ─────────────────────────────────────────────\n"
        "  O navegador abre automaticamente com um assistente\n"
        "  guiado. Siga as 4 telas: placa de captura, monitor,\n"
        "  delay, e clique em \"Iniciar\". Pronto.\n"
        "\n"
        "  SUPORTE\n"
        "  ─────────────────────────────────────────────\n"
        "  contato@estudioab.io\n",
        encoding="utf-8",
    )
    return path


def zip_distribution(target: str) -> Path:
    """Empacota o output do PyInstaller em um único .zip com INSTALL.txt."""
    dist = ROOT / "dist"
    install_txt = write_install_txt()

    if sys.platform == "darwin":
        out_zip = dist / f"{APP_NAME}-mac.zip"
        app_path = dist / f"{APP_NAME}.app"
        if not app_path.is_dir():
            raise RuntimeError(f"Build não produziu {app_path}")
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for root, _, files in os.walk(app_path):
                for f in files:
                    full = Path(root) / f
                    rel = full.relative_to(dist)
                    z.write(full, arcname=str(rel))
            z.write(install_txt, arcname="INSTALL.txt")
        return out_zip

    if sys.platform == "win32":
        out_zip = dist / f"{APP_NAME}-win.zip"
        folder = dist / APP_NAME
        if not folder.is_dir():
            raise RuntimeError(f"Build não produziu {folder}")
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for root, _, files in os.walk(folder):
                for f in files:
                    full = Path(root) / f
                    rel = full.relative_to(dist)
                    z.write(full, arcname=str(rel))
            z.write(install_txt, arcname="INSTALL.txt")
        return out_zip

    raise RuntimeError(f"Plataforma não suportada para zip: {sys.platform}")


# ──────────────────────────────────────────────────────────────────────
#  Entrypoint
# ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Build do executável do Video Delay System")
    parser.add_argument("--clean", action="store_true", help="limpa artefatos antes")
    parser.add_argument("--console", action="store_true", help="mantém terminal visível")
    parser.add_argument("--skip-zip", action="store_true", help="pula a etapa de zip")
    parser.add_argument("--skip-fetch", action="store_true", help="não baixa binários (assume vendor pronto)")
    args = parser.parse_args()

    target = detect_target()
    print(f"→ Target: {target}")

    if args.clean:
        clean()

    if not have_pyinstaller():
        install_pyinstaller()

    if not have_vendor(target):
        if args.skip_fetch:
            raise SystemExit(
                f"vendor/{target}/ não encontrado e --skip-fetch foi passado. "
                f"Rode `python scripts/fetch_binaries.py --target {target}` antes."
            )
        fetch_vendor(target)
        if not have_vendor(target):
            raise SystemExit(f"fetch_binaries falhou — vendor/{target}/ ainda vazio")

    maybe_generate_icons()

    cmd = build_command(target, args)
    print("→ PyInstaller:")
    print("  " + " ".join(cmd))
    print()
    subprocess.check_call(cmd, cwd=ROOT)
    print()

    patch_info_plist()

    if not args.skip_zip:
        out_zip = zip_distribution(target)
        size_mb = out_zip.stat().st_size // 1024 // 1024
        print(f"→ Distribuição empacotada: {out_zip}  ({size_mb}MB)")
    else:
        print(f"→ Skipped zip — bundle disponível em {ROOT/'dist'}")

    print()
    print("→ Build concluído.")
    print()
    if sys.platform == "darwin":
        print(f"  Para testar:  open dist/{APP_NAME}.app")
    elif sys.platform == "win32":
        print(f"  Para testar:  dist\\{APP_NAME}\\{APP_NAME}.exe")


if __name__ == "__main__":
    main()
