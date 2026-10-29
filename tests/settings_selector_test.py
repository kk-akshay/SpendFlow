"""Prevent regressions where Settings iterates over a single DOM node.

No additional dependencies: exercise the same DOM selector semantics as browsers.
"""
from pathlib import Path

source = (Path(__file__).resolve().parent.parent / "frontend" / "pages.js").read_text(encoding="utf-8")
assert "$$('[data-rule-cat]').forEach(" in source, "Settings must iterate a NodeList, not a single element"
assert "$('[data-rule-cat]').forEach(" not in source.replace("$$('[data-rule-cat]').forEach(", ""), "Unsafe selector iteration returned"
print("Settings selector regression check passed")
