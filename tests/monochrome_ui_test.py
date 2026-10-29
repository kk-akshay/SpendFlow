"""Monochrome token and SVG chart regression checks (no browser dependencies)."""
from pathlib import Path
root=Path(__file__).resolve().parents[1]/"frontend"
css=(root/"app.css").read_text(encoding="utf-8")
pages=(root/"pages.js").read_text(encoding="utf-8")
review=(root/"review.js").read_text(encoding="utf-8")
core=(root/"app.js").read_text(encoding="utf-8")
for token in ("--bg:#F8F9FA","--surface:#FFFFFF","--line:#E4E4E7","--text:#09090B",
              "--muted:#71717A","--bg:#121316","--surface:#1E2025","--input:#2A2C33",
              "--line:#3A3D46","--text:#FAFAFA","--muted:#9496A1"):
    assert token in css,token
assert "color-scheme:dark" in css and 'data-theme="dark"' in css
assert ".btn.primary{background:var(--accent);color:var(--accent-ink)" in css
assert "cashflow-gradient" in pages and "pace-gradient" in pages
assert "smoothLine" in pages and "cashflow-muted" in pages
assert "↑ +" in pages and "↓ −" in pages and "↑ +" in review and "↓ −" in review
assert "background:${esc(b.color)}" not in pages
assert "background:${esc(r.category_color" not in pages
assert "background:${esc(t.category_color" not in pages
assert "style=\"--c:${esc(c.color)}\"" not in review
assert "background:${esc(sgCat.color)}" not in review
assert "style=\"background:${esc(c?.color" not in core
assert "spendflow-theme" in core and "spendflow-theme" in (root/"index.html").read_text()
print("Monochrome theme regressions passed")
