// Inlines the AB symbol into elements with id="glyph-top"/"glyph-bot"
// so that `currentColor` can paint the glyph against any ground.
// Uses fetch instead of `mask-image` because mask-image renders the SVG
// against its own root colour, not the parent's color.
(async () => {
  try {
    const res = await fetch('assets/symbol.svg', { cache: 'force-cache' });
    if (!res.ok) return;
    const svg = await res.text();
    document.querySelectorAll('.glyph').forEach(el => {
      el.innerHTML = svg;
    });
  } catch {
    // assets opcionais — silencioso se faltarem
  }
})();
