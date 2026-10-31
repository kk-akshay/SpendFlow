"""Guard actual link action and multi-tag refund editing against wrong DOM selector."""
from pathlib import Path
root=Path(__file__).resolve().parents[1]/"frontend"
p=(root/"pages.js").read_text(encoding="utf-8")
app=(root/"app.js").read_text(encoding="utf-8")
assert "$$('[data-link-refund]',dlg.el).forEach" in p
assert "tag_ids:$$('[data-assign-tag]:checked',m.el).map" in p
assert "['income', 'transfer', 'refund', 'expense']" in p
assert "value !== 'refund'" in p
assert "document.activeElement === active" in app
print("Refund interaction selector checks passed.")
