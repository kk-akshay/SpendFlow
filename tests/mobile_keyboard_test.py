"""Keyboard regression guards for shared mobile viewport support."""
from pathlib import Path
root=Path(__file__).resolve().parents[1]/"frontend"
js=(root/"app.js").read_text(encoding="utf-8")
css=(root/"app.css").read_text(encoding="utf-8")
pages=(root/"pages.js").read_text(encoding="utf-8")
assert "visualViewport" in js and "addEventListener('resize'" in js
assert "addEventListener('focusin'" in js and "scrollIntoView" in js
assert "--keyboard-viewport-height" in css and "overflow-y:auto" in css
assert "position:sticky" in css and "font-size:16px" in css
assert "openRefundLink" in pages and "Skip linking" in pages
print("Mobile viewport and refund UI static checks passed.")
