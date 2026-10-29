"""Guard known multi-select controls against null single-node iteration."""
from pathlib import Path
root=Path(__file__).resolve().parent.parent/"frontend"
for filename, selectors, operation in (
    ("people.js", ("[data-person-find]", "[data-alias-del]"), "forEach"),
    ("people.js", ("[data-candidate-role]",), "filter"),
    ("pages.js", ("[data-flow-txn]:checked", "[data-match]:checked"), "map"),
):
    source=(root/filename).read_text(encoding="utf-8")
    for selector in selectors:
        assert "$$('" + selector + "'" in source, (filename, selector, "collection selector missing")
        assert "$('" + selector + "'" not in source.replace("$$('" + selector + "'", ""), (filename, selector, "unsafe single selector")
print("People & Loans selector regression check passed")
