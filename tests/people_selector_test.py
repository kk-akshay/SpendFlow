"""Guard browser selector collection usage against null .forEach/.filter/.map."""
from pathlib import Path
import re
root=Path(__file__).resolve().parent.parent/"frontend"
for name in ("people.js","pages.js"):
    source=(root/name).read_text(encoding="utf-8")
    errors=re.findall(r"(?<!\$)\$\([^\n;]*?\)\.(?:forEach|filter|map)\(", source)
    assert not errors,(name,errors)
print("Collection selector checks passed")
