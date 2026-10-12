"""Bank statement parsing.

Strategy 1 (columns): find the header row (Date / Narration / Debit / Credit / Balance) and use the
horizontal position of each header to decide which column every amount sits in. This is the most
reliable approach because it doesn't need to guess whether a number is a debit or a credit.

Strategy 2 (text): for statements without a recognisable header (or messy OCR), read each date-led
block as text and work out debit/credit from the running balance, Dr/Cr markers and keywords.

Either way the running balance is used afterwards to verify (and correct) each row's direction.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import median

from .extract import Page, Word
from .parse_common import Line, group_lines, leading_date, parse_amount, parse_date

DEBIT_WORDS = {"debit", "debits", "withdrawal", "withdrawals", "withdrawn", "dr"}
CREDIT_WORDS = {"credit", "credits", "deposit", "deposits", "cr"}
BAL_WORDS = {"balance", "bal"}
AMT_WORDS = {"amount", "amt"}

FOOTER_HINTS = (
    "opening balance", "closing balance", "page ", "statement summary", "total", "generated on",
    "registered office", "toll free", "www.", "this is a computer", "end of statement", "ifsc",
    "customer id", "account number", "account no", "carried forward", "brought forward",
)

DEBIT_HINTS = {"debit", "withdrawal", "atm", "pos", "paid", "purchase", "sent", "nach", "emi", "charges",
               "fee", "fees", "chq", "dr", "wdl", "bill"}
CREDIT_HINTS = {"credit", "deposit", "salary", "interest", "refund", "cashback", "received", "reversal",
                "cr", "int", "dividend"}


DATE_LOST = "The date couldn't be read. The previous row's date was used. Please check"


@dataclass
class Header:
    cols: dict           # name -> (x0_frac, x1_frac)
    zone_start: float    # amounts live to the right of this (fraction of page width)
    value_x: float | None = None   # x of a "Value Date" column, whose dates must not leak into narrations

    def nearest(self, w: Word, width: float) -> str:
        c = (w.x0 + w.x1) / 2 / width
        r = w.x1 / width
        best, dist = None, 9.0
        for name, (a, b) in self.cols.items():
            d = min(abs(c - (a + b) / 2), abs(r - b))
            if d < dist:
                best, dist = name, d
        return best or "amount"


def _clean(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


def detect_header(line: Line, width: float) -> Header | None:
    toks = [(_clean(w.text), w) for w in line.words]
    names = {t for t, _ in toks}
    if "date" not in names and "dt" not in names:
        return None
    groups: dict[str, list[Word]] = {"debit": [], "credit": [], "balance": [], "amount": []}
    for t, w in toks:
        if t in DEBIT_WORDS:
            groups["debit"].append(w)
        elif t in CREDIT_WORDS:
            groups["credit"].append(w)
        elif t in BAL_WORDS:
            groups["balance"].append(w)
        elif t in AMT_WORDS:
            groups["amount"].append(w)
    if not (groups["debit"] or groups["credit"] or groups["amount"]):
        return None
    if groups["debit"] or groups["credit"]:
        # "Withdrawal Amt." / "Deposit Amt.": fold the Amt word into the column to its left
        for aw in groups["amount"]:
            left = [(aw.x0 - ww.x1, k) for k in ("debit", "credit") for ww in groups[k] if 0 <= aw.x0 - ww.x1 < 0.12 * width]
            if left:
                groups[min(left)[1]].append(aw)
        groups["amount"] = []
    cols = {}
    for name, ws in groups.items():
        if ws:
            cols[name] = (min(w.x0 for w in ws) / width, max(w.x1 for w in ws) / width)
    if len(cols) < 1:
        return None
    zone_start = min(a for a, _ in cols.values()) - 0.03
    value_x = next((w.x0 / width for t, w in toks if t == "value"), None)
    return Header(cols, zone_start, value_x)


def _drcr_word(text: str) -> str | None:
    t = text.lower().strip(".")
    return {"dr": "debit", "cr": "credit"}.get(t)


def parse_columnar(pages: list[Page]) -> list[dict]:
    header: Header | None = None
    raw: list[dict] = []
    cur: dict | None = None
    last_bottom = 0.0
    for pno, page in enumerate(pages):
        W = page.width or max((w.x1 for w in page.words), default=1.0)
        lines = group_lines(page, pno)
        if not lines:
            continue
        medh = median(max(l.bottom - l.top, 1) for l in lines)
        for line in lines:
            h = detect_header(line, W)
            if h:
                header, cur = h, None
                continue
            if header is None:
                continue
            low = line.text.lower()
            ld = leading_date(line.words, W)
            if ld:
                iso, n = ld
                rest = line.words[n:]
                # A second date straight after the first is a "value date" column: drop it.
                if rest:
                    for k in (1, 2, 3):
                        if k <= len(rest) and parse_date(" ".join(w.text for w in rest[:k])):
                            rest = rest[k:]
                            break
                desc, amounts = [], []
                for w in rest:
                    if header.value_x is not None and abs(w.x0 / W - header.value_x) < 0.06 and parse_date(w.text):
                        continue
                    if w.x0 / W >= header.zone_start:
                        a = parse_amount(w.text)
                        if a:
                            amounts.append((header.nearest(w, W), a[0], a[1]))
                            continue
                        dc = _drcr_word(w.text)
                        if dc:
                            amounts.append(("marker", 0, dc))
                            continue
                    desc.append(w.text)
                cur = {"date": iso, "desc": desc, "amounts": amounts}
                raw.append(cur)
                last_bottom = line.bottom
            else:
                if any(f in low for f in FOOTER_HINTS) or re.fullmatch(r"[-=_*\s]*", low):
                    cur = None
                    continue
                zone_amts = [w for w in line.words if w.x0 / W >= header.zone_start and parse_amount(w.text)]
                if zone_amts and raw:
                    # An amount with no readable date (typical of OCR): keep the row rather than lose it,
                    # borrow the previous date and flag it so the user checks it.
                    desc, amounts = [], []
                    for w in line.words:
                        if w.x0 / W >= header.zone_start:
                            a = parse_amount(w.text)
                            if a:
                                amounts.append((header.nearest(w, W), a[0], a[1]))
                                continue
                            dc = _drcr_word(w.text)
                            if dc:
                                amounts.append(("marker", 0, dc))
                                continue
                        if not parse_date(w.text.strip(";:,")):
                            desc.append(w.text)
                    cur = {"date": raw[-1]["date"], "desc": desc, "amounts": amounts, "flags": [DATE_LOST]}
                    raw.append(cur)
                    last_bottom = line.bottom
                    continue
                if cur is None:
                    continue
                if line.top - last_bottom > 2.4 * medh:
                    cur = None
                    continue
                add = [w.text for w in line.words if w.x0 / W < header.zone_start]
                if add:
                    cur["desc"].extend(add)
                    last_bottom = line.bottom
    return raw


def _raw_to_rows(raw: list[dict]) -> list[dict]:
    rows = []
    for r in raw:
        debit = credit = amount = balance = None
        marker = None
        for col, minor, dc in r["amounts"]:
            if col == "marker":
                marker = dc
            elif col == "debit" and minor:
                debit = debit or minor
            elif col == "credit" and minor:
                credit = credit or minor
            elif col == "balance":
                balance = -minor if dc == "debit" else minor
            elif col == "amount" and minor:
                amount = amount or minor
                marker = marker or dc
        flags = list(r.get("flags", []))
        if debit and credit:
            flags.append("Both a debit and a credit were found on this row")
        if debit:
            amt, direction = debit, "debit"
        elif credit:
            amt, direction = credit, "credit"
        elif amount:
            amt, direction = amount, marker
        else:
            continue
        rows.append({
            "date": r["date"],
            "description": re.sub(r"\s+", " ", " ".join(r["desc"])).strip(),
            "amount_minor": amt,
            "direction": direction,
            "balance_minor": balance,
            "flags": flags,
        })
    return rows


def parse_text_blocks(pages: list[Page]) -> list[dict]:
    """Fallback: date-led blocks of text."""
    rows: list[dict] = []
    cur: dict | None = None

    def flush():
        nonlocal cur
        if not cur:
            return
        toks = cur["tokens"]
        amts = []
        for i, t in enumerate(toks):
            a = parse_amount(t)
            if a:
                amts.append([i, a[0], a[1]])
            elif _drcr_word(t) and amts and amts[-1][2] is None and amts[-1][0] == i - 1:
                amts[-1][2] = _drcr_word(t)
        extra = cur["extra"]
        date_iso = cur["date"]
        cur = None
        if not amts:
            return
        if len(amts) >= 2:
            b = amts[-1]
            balance = -b[1] if b[2] == "debit" else b[1]
            candidates = [a for a in amts[:-1] if a[1] > 0]
        else:
            balance = None
            candidates = [a for a in amts if a[1] > 0]
        if not candidates:
            return
        a = candidates[0]
        desc_tokens = toks[: amts[0][0]] + extra
        rows.append({
            "date": date_iso,
            "description": re.sub(r"\s+", " ", " ".join(desc_tokens)).strip(),
            "amount_minor": a[1],
            "direction": a[2],
            "balance_minor": balance,
            "flags": [],
        })

    for pno, page in enumerate(pages):
        W = page.width or 1.0
        for line in group_lines(page, pno):
            ld = leading_date(line.words, W, max_x_frac=0.5)
            if ld:
                flush()
                iso, n = ld
                rest = line.words[n:]
                for k in (1, 2, 3):
                    if k <= len(rest) and parse_date(" ".join(w.text for w in rest[:k])):
                        rest = rest[k:]
                        break
                cur = {"date": iso, "tokens": [w.text for w in rest], "extra": []}
            elif cur is not None:
                low = line.text.lower()
                if any(f in low for f in FOOTER_HINTS):
                    flush()
                    continue
                cur["extra"].extend(w.text for w in line.words if parse_amount(w.text) is None)
        flush()
    return rows


def find_opening_balance(pages: list[Page]) -> int | None:
    for pno, page in enumerate(pages[:3]):
        lines = group_lines(page, pno)
        for i, line in enumerate(lines):
            if "opening balance" in line.text.lower() or "balance b/f" in line.text.lower():
                for l in (line, lines[i + 1] if i + 1 < len(lines) else None):
                    if not l:
                        continue
                    for w in l.words:
                        a = parse_amount(w.text)
                        if a:
                            return -a[0] if a[1] == "debit" else a[0]
    return None


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def guess_direction(description: str) -> str | None:
    w = _words(description)
    d, c = len(w & DEBIT_HINTS), len(w & CREDIT_HINTS)
    if re.search(r"(?i)upi/dr|/dr/|\bdr\b", description):
        d += 2
    if re.search(r"(?i)upi/cr|/cr/|\bcr\b", description):
        c += 2
    if d > c:
        return "debit"
    if c > d:
        return "credit"
    return None


def resolve_directions(rows: list[dict], opening: int | None) -> list[str]:
    """Use the running balance to verify/derive each row's direction. Returns statement-level warnings."""
    warnings: list[str] = []
    n = len(rows)
    mode = None
    pairs = asc = desc = 0
    for i in range(1, n):
        a, b = rows[i - 1], rows[i]
        if a["balance_minor"] is None or b["balance_minor"] is None:
            continue
        pairs += 1
        if abs(b["balance_minor"] - a["balance_minor"]) == b["amount_minor"]:
            asc += 1
        if abs(a["balance_minor"] - b["balance_minor"]) == a["amount_minor"]:
            desc += 1
    if pairs >= 2 and max(asc, desc) >= 0.5 * pairs:
        mode = "asc" if asc >= desc else "desc"

    if mode:
        bad = 0
        for i, r in enumerate(rows):
            if mode == "asc":
                prev = rows[i - 1]["balance_minor"] if i > 0 else opening
                ok = prev is not None and r["balance_minor"] is not None and abs(r["balance_minor"] - prev) == r["amount_minor"]
                new = ("credit" if r["balance_minor"] > prev else "debit") if ok else None
            else:
                nxt = rows[i + 1]["balance_minor"] if i + 1 < n else opening
                ok = nxt is not None and r["balance_minor"] is not None and abs(r["balance_minor"] - nxt) == r["amount_minor"]
                new = ("credit" if r["balance_minor"] > nxt else "debit") if ok else None
            if ok:
                if r["direction"] and r["direction"] != new:
                    r["flags"].append("Debit/credit corrected using the running balance")
                r["direction"] = new
            else:
                # first/last row can't be checked without an opening balance; don't alarm for that
                edge = (mode == "asc" and i == 0) or (mode == "desc" and i == n - 1)
                if not edge:
                    bad += 1
                    r["flags"].append("Doesn't match the running balance. Please check this row")
        if bad:
            warnings.append(f"{bad} of {n} rows didn't match the running balance. They're marked so you can check them.")
    elif any(r["balance_minor"] is not None for r in rows):
        warnings.append("The balance column couldn't be used to verify this statement.")

    for r in rows:
        if r["direction"] is None:
            g = guess_direction(r["description"])
            if g:
                r["direction"] = g
                r["flags"].append("Debit/credit guessed from the description. Please check")
            else:
                r["direction"] = "debit"
                r["flags"].append("Couldn't tell if this was money in or out. Assumed money out")
    return warnings


def parse_bank(pages: list[Page]) -> tuple[list[dict], list[str], str]:
    raw = parse_columnar(pages)
    rows = _raw_to_rows(raw)
    parser = "columns"
    if not rows:
        rows = parse_text_blocks(pages)
        parser = "text"
    opening = find_opening_balance(pages)
    warnings = resolve_directions(rows, opening) if rows else []
    for r in rows:
        m = re.search(r"(?<!\d)(\d{12})(?!\d)", r["description"])
        r["ref"] = m.group(1) if m else None
    return rows, warnings, parser
