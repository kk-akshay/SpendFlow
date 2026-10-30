"""Regression checks for responsive SpendFlow navigation shell."""
from pathlib import Path
root=Path(__file__).resolve().parents[1]/"frontend"
shell=(root/"shell.js").read_text(encoding="utf-8")
app=(root/"app.js").read_text(encoding="utf-8")
css=(root/"app.css").read_text(encoding="utf-8")
html=(root/"index.html").read_text(encoding="utf-8")
assert '<script src="/shell.js' in html and ('/shell.js"></script>' in html or '/shell.js?v=' in html)
assert 'href="/brand.svg"' in html
assert 'fill="currentColor"' in (root/"brand.svg").read_text()
for name in ("dashboard","transactions","groups","calendar"):
    assert "['"+name+"'," in shell
for name in ("review","people","plan","settings"):
    assert "['"+name+"'," in shell
assert "['groups','Linked Money']" in shell
assert "groups:" in shell and "viewBox=\"0 0 24 24\"" in shell
assert "grid-template-columns:repeat(5,minmax(0,1fr))" in css
assert "backdrop-filter:blur(16px)" in css
assert "env(safe-area-inset-bottom)" in css
assert "mobile-more-overlay:not([hidden])" in css
assert "role=\"dialog\"" in shell and "aria-expanded" in shell
assert "aria-current" in app and "closeMore(false)" in app
assert "syncThemeButton" in app and "setTheme(next)" in app
assert "color-scheme:dark" in css
assert "#121316" in css and "#F8F9FA" in css
assert 'href="/api/export.csv"' in (root/"pages.js").read_text(encoding="utf-8")
assert "mobile-export" not in shell
assert "['accounts','Accounts']" in shell
print("Responsive navigation checks passed")
