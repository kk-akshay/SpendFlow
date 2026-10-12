"""Shared helpers: dates, amounts, line grouping."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from .extract import Page, Word

_FULL_MONTHS = ["january", "february", "march", "april", "may", "june", "july",
                "august", "september", "october", "november", "december"]


def month_number(token: str) -> int | None:
    t = token.lower().strip(".,")
    if len(t) < 3:
        return None
    for i, name in enumerate(_FULL_MONTHS, 1):
        if name.startswith(t):
            return i
    return None


def _mk(y: int, m: int, d: int) -> str | None:
    if y < 100:
        y += 2000
    if not 1990 <= y <= 2100:
        return None
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


_NUM_DATE = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})$")
_ISO_DATE = re.compile(r"^(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})$")
_TXT_DATE = re.compile(r"^(\d{1,2})[\s\-./]*([A-Za-z]{3,9})\.?,?[\s\-./]*(\d{2,4})$")
_TXT_DATE2 = re.compile(r"^([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})$")


def parse_date(s: str) -> str | None:
    """Parse a date string (day-first for numeric forms, as is standard in India) to ISO."""
    s = s.strip().rstrip(",")
    if m := _NUM_DATE.match(s):
        d, mo, y = int(m[1]), int(m[2]), int(m[3])
        if mo > 12 and d <= 12:
            d, mo = mo, d
        return _mk(y, mo, d)
    if m := _ISO_DATE.match(s):
        return _mk(int(m[1]), int(m[2]), int(m[3]))
    if m := _TXT_DATE.match(s):
        mo = month_number(m[2])
        return _mk(int(m[3]), mo, int(m[1])) if mo else None
    if m := _TXT_DATE2.match(s):
        mo = month_number(m[1])
        return _mk(int(m[3]), mo, int(m[2])) if mo else None
    return None


def parse_time(s: str) -> str | None:
    m = re.search(r"\b(\d{1,2}):(\d{2})\s?(AM|PM|am|pm)?\b", s)
    if not m:
        return None
    h, mi, ap = int(m[1]), int(m[2]), (m[3] or "").upper()
    if ap == "PM" and h < 12:
        h += 12
    if ap == "AM" and h == 12:
        h = 0
    if h > 23 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}"


def to_minor(text: str) -> int:
    return int((Decimal(text.replace(",", "")) * 100).quantize(Decimal(1), ROUND_HALF_UP))


# Bank statements always print two decimals, which separates amounts from reference numbers.
_AMT = re.compile(
    r"^\(?(-)?(?:₹|Rs\.?|INR)?\s?((?:\d{1,3}(?:,\d{2,3})+|\d+)\.\d{2})\)?(?:\s?(Dr|Cr|DR|CR|dr|cr)\.?)?$"
)


def parse_amount(token: str) -> tuple[int, str | None] | None:
    """Return (minor_units, 'debit'|'credit'|None) for a strict statement amount token."""
    t = token.strip()
    m = _AMT.match(t)
    if not m:
        return None
    minor = to_minor(m.group(2))
    marker = m.group(3)
    if marker:
        return minor, "debit" if marker.lower() == "dr" else "credit"
    if m.group(1) or t.startswith("("):
        return minor, "debit"
    return minor, None


@dataclass
class Line:
    words: list[Word]
    text: str
    cy: float
    top: float
    bottom: float
    page: int


def group_lines(page: Page, page_no: int = 0) -> list[Line]:
    ws = sorted(page.words, key=lambda w: ((w.top + w.bottom) / 2, w.x0))
    if not ws:
        return []
    med = median(max(w.bottom - w.top, 1) for w in ws)
    tol = med * 0.6
    groups: list[list[Word]] = []
    cur = [ws[0]]
    cy = (ws[0].top + ws[0].bottom) / 2
    for w in ws[1:]:
        wcy = (w.top + w.bottom) / 2
        if abs(wcy - cy) <= tol:
            cur.append(w)
            cy = sum((x.top + x.bottom) / 2 for x in cur) / len(cur)
        else:
            groups.append(cur)
            cur, cy = [w], wcy
    groups.append(cur)
    out = []
    for g in groups:
        g.sort(key=lambda w: w.x0)
        out.append(Line(g, " ".join(w.text for w in g), cy, min(w.top for w in g), max(w.bottom for w in g), page_no))
    return out


def leading_date(words: list[Word], page_width: float, max_x_frac: float = 0.4) -> tuple[str, int] | None:
    """If the line starts with a date, return (iso, number_of_words_it_spans)."""
    if not words or words[0].x0 / (page_width or 1) > max_x_frac:
        return None
    for k in (1, 2, 3):
        if k > len(words):
            break
        iso = parse_date(" ".join(w.text for w in words[:k]))
        if iso:
            return iso, k
    return None
