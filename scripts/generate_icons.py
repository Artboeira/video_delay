"""
scripts/generate_icons.py — Gera `symbol.icns` (Mac) e `symbol.ico` (Win) a
partir do `webui/assets/symbol.svg` para o PyInstaller usar no ícone do app.

Dependência build-time: `pip install pillow cairosvg`. O `build.py` invoca este
script automaticamente antes do PyInstaller se os ícones não existirem.

Saída:
    webui/assets/symbol.icns
    webui/assets/symbol.ico

Idempotente — se ambos os ícones já existem, é no-op. Use `--force` para refazer.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SVG_SRC = ROOT / "webui" / "assets" / "symbol.svg"
ICNS_OUT = ROOT / "webui" / "assets" / "symbol.icns"
ICO_OUT = ROOT / "webui" / "assets" / "symbol.ico"


# Cor do glyph: tinta AB (ink) sobre fundo bone. Ícones de macOS são geralmente
# vistos contra um fundo claro do Dock, então o ink dá contraste melhor.
INK_RGB = (34, 34, 35)        # --ab-ink
BONE_RGBA = (237, 229, 211, 255)  # --ab-bone


def rasterize_svg(size: int) -> "Image.Image":
    """Renderiza symbol.svg em uma imagem quadrada de `size`px com fundo bone."""
    try:
        import cairosvg
        from PIL import Image
        from io import BytesIO
    except ImportError as e:
        raise SystemExit(
            f"Faltando dependência build-time: {e.name}. "
            f"Rode: pip install pillow cairosvg"
        )

    # cairosvg respeita o viewBox e gera uma imagem RGBA com fundo transparente.
    png_bytes = cairosvg.svg2png(
        url=str(SVG_SRC),
        output_width=size,
        output_height=size,
    )
    glyph = Image.open(BytesIO(png_bytes)).convert("RGBA")

    # Aplica cor ink no glyph (que vem em currentColor → preto puro)
    pixels = glyph.load()
    for y in range(glyph.height):
        for x in range(glyph.width):
            r, g, b, a = pixels[x, y]
            if a > 0:
                pixels[x, y] = (*INK_RGB, a)

    # Fundo bone com leve padding (10% das bordas para o glyph respirar)
    canvas = Image.new("RGBA", (size, size), BONE_RGBA)
    pad = size // 10
    glyph_inset = glyph.resize((size - 2 * pad, size - 2 * pad), Image.LANCZOS)
    canvas.paste(glyph_inset, (pad, pad), glyph_inset)
    return canvas


def generate_icns(force: bool):
    if ICNS_OUT.exists() and not force:
        print(f"  ✓ {ICNS_OUT.name} já existe")
        return
    if sys.platform != "darwin":
        print(f"  ⚠ pulando {ICNS_OUT.name} (precisa de iconutil, só em macOS)")
        return
    if not shutil.which("iconutil"):
        print(f"  ⚠ iconutil ausente — pulando {ICNS_OUT.name}")
        return

    with tempfile.TemporaryDirectory() as td:
        iconset = Path(td) / "symbol.iconset"
        iconset.mkdir()
        for size, name in [
            (16, "icon_16x16.png"),
            (32, "icon_16x16@2x.png"),
            (32, "icon_32x32.png"),
            (64, "icon_32x32@2x.png"),
            (128, "icon_128x128.png"),
            (256, "icon_128x128@2x.png"),
            (256, "icon_256x256.png"),
            (512, "icon_256x256@2x.png"),
            (512, "icon_512x512.png"),
            (1024, "icon_512x512@2x.png"),
        ]:
            img = rasterize_svg(size)
            img.save(iconset / name, "PNG")
        subprocess.check_call(["iconutil", "-c", "icns", str(iconset),
                               "-o", str(ICNS_OUT)])
    print(f"  ✓ gerado {ICNS_OUT.name}")


def generate_ico(force: bool):
    if ICO_OUT.exists() and not force:
        print(f"  ✓ {ICO_OUT.name} já existe")
        return
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        raise SystemExit("Faltando dependência: pip install pillow cairosvg")

    # Pillow aceita múltiplos tamanhos num único .ico
    sizes = [16, 32, 48, 64, 128, 256]
    base = rasterize_svg(256)
    base.save(
        ICO_OUT,
        format="ICO",
        sizes=[(s, s) for s in sizes],
    )
    print(f"  ✓ gerado {ICO_OUT.name}")


def main():
    parser = argparse.ArgumentParser(description="Gera ícones .icns/.ico do app")
    parser.add_argument("--force", action="store_true", help="refaz mesmo se já existem")
    args = parser.parse_args()

    if not SVG_SRC.exists():
        raise SystemExit(f"SVG fonte não encontrado: {SVG_SRC}")

    print(f"→ Gerando ícones a partir de {SVG_SRC}")
    generate_icns(args.force)
    generate_ico(args.force)
    print("→ Pronto.")


if __name__ == "__main__":
    main()
