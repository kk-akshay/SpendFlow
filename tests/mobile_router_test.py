"""Guard the router against single-element selectors with array iteration."""
from pathlib import Path
s=(Path(__file__).resolve().parents[1]/"frontend/app.js").read_text()
dollar=chr(36)
assert dollar*2+"('.nav a.item,.mobile-nav a.item').forEach" in s
assert dollar*2+"('[data-more-link]').forEach" in s
assert dollar+"('.nav a.item,.mobile-nav a.item').forEach" not in s.replace(dollar*2+"('.nav a.item,.mobile-nav a.item').forEach","")
assert dollar+"('[data-more-link]').forEach" not in s.replace(dollar*2+"('[data-more-link]').forEach","")
print("Router navigation collection checks passed")
