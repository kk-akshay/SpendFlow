"""Orchestrates: extract text -> detect source -> parse -> validate -> enrich rows."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import parse_llm, parse_card
from .extract import Extracted, extract_document
from .merchants import extract_merchant, merchant_key
from .parse_bank import parse_bank
from .parse_common import group_lines, leading_date
from .parse_gpay import looks_like_gpay, parse_gpay

BANK_NAMES = [
    ("HDFC", r"hdfc"), ("ICICI", r"icici"), ("SBI", r"state bank of india|\bsbi\b"), ("Axis", r"axis bank"),
    ("Kotak", r"kotak"), ("Federal Bank", r"federal bank"), ("Canara", r"canara"), ("Union Bank", r"union bank"),
    ("IDFC First", r"idfc"), ("Yes Bank", r"yes bank"), ("PNB", r"punjab national|\bpnb\b"),
    ("Bank of Baroda", r"bank of baroda"), ("South Indian Bank", r"south indian bank"),
    ("IndusInd", r"indusind"), ("Indian Bank", r"indian bank"), ("Karnataka Bank", r"karnataka bank"),
]

MAX_ROWS = 5000


@dataclass
class ParseResult:
    source_type: str = "bank"
    parser: str = "columns"
    rows: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    account_name: str | None = None
    account_last4: str | None = None
    ocr_used: bool = False
    card_info: dict = field(default_factory=dict)


def _head_text(ex: Extracted, pages: int = 2) -> str:
    out = []
    for pno, p in enumerate(ex.pages[:pages]):
        out.extend(l.text for l in group_lines(p, pno))
    return "\n".join(out)


def _preamble(ex: Extracted) -> str:
    """Text above the first transaction line (bank name, account number), so narrations can't confuse the guess."""
    if not ex.pages:
        return ""
    page = ex.pages[0]
    out = []
    for line in group_lines(page, 0)[:40]:
        if leading_date(line.words, page.width or 1):
            break
        out.append(line.text)
    return "\n".join(out)


def _guess_account(head: str) -> tuple[str | None, str | None]:
    low = head.lower()
    bank = next((n for n, pat in BANK_NAMES if re.search(pat, low)), None)
    m = re.search(r"(?i)(?:a/c|account)\s*(?:no|number|#)?\.?\s*[:\-]?\s*[xX*\d\s]*?(\d{4})\b", head)
    return bank, (m.group(1) if m else None)


def _validate(rows: list[dict]) -> tuple[list[dict], int]:
    good, dropped = [], 0
    for r in rows:
        if not r.get("date") or not r.get("amount_minor") or r["amount_minor"] <= 0 or r["amount_minor"] > 10**13:
            dropped += 1
            continue
        if r.get("direction") not in ("debit", "credit"):
            dropped += 1
            continue
        r["description"] = (r.get("description") or "")[:500]
        good.append(r)
    return good[:MAX_ROWS], dropped


def _flag_date_outliers(rows: list[dict]) -> int:
    """Flag rows whose date is far from where nearly all the other rows cluster (often an OCR misread year)."""
    from datetime import date

    if len(rows) < 6:
        return 0
    ords = sorted(date.fromisoformat(r["date"]).toordinal() for r in rows)
    med = ords[len(ords) // 2]
    near = sum(1 for o in ords if abs(o - med) <= 120)
    if near < 0.8 * len(ords):
        return 0
    n = 0
    for r in rows:
        if abs(date.fromisoformat(r["date"]).toordinal() - med) > 120:
            r["flags"].append("This date is far from the others. Please check")
            n += 1
    return n


def parse_file(path: str, kind: str, password: str | None = None, use_ai: bool = False) -> ParseResult:
    ex = extract_document(path, kind, password)
    res = ParseResult(warnings=list(ex.warnings), ocr_used=ex.ocr_used)
    head = _head_text(ex)
    gpay_hint = looks_like_gpay(head)

    card_info = parse_card.detect_card(ex.pages)
    if card_info:
        rows, card_warnings, info = parse_card.parse_card(ex.pages)
        res.parser, res.source_type, res.card_info = "supercard", "card", info
        res.warnings.extend(card_warnings)
        rows, dropped = _validate(rows)
        if dropped: res.warnings.append(f"{dropped} card row(s) could not be validated.")
        for r in rows:
            r.setdefault("flags", [])
            r.setdefault("ref", None)
            r.setdefault("time", None)
            r["merchant"] = extract_merchant(r["description"])
            r["merchant_key"] = merchant_key(r["merchant"])
        res.rows = rows
        res.account_name = info["name"]
        res.account_last4 = info["last4"]
        return res

    rows: list[dict] = []
    if use_ai and parse_llm.available():
        try:
            rows = parse_llm.parse_with_llm(ex.pages)
            res.parser = "ai"
            res.source_type = "gpay" if gpay_hint else "bank"
            if not rows:
                res.warnings.append("The AI step returned no transactions, so the built-in reader was used instead.")
        except Exception:
            res.warnings.append("The AI step failed, so the built-in reader was used instead.")
            rows = []

    if not rows:
        gp_rows, gp_warn = parse_gpay(ex.pages) if gpay_hint else ([], [])
        bank_rows, bank_warn, bank_parser = ([], [], "columns")
        if not gpay_hint or not gp_rows:
            bank_rows, bank_warn, bank_parser = parse_bank(ex.pages)
        if gpay_hint and len(gp_rows) >= len(bank_rows):
            rows, res.source_type, res.parser = gp_rows, "gpay", "gpay"
            res.warnings += gp_warn
        else:
            rows, res.source_type, res.parser = bank_rows, "bank", bank_parser
            res.warnings += bank_warn

    rows, dropped = _validate(rows)
    odd = _flag_date_outliers(rows)
    if odd:
        res.warnings.append(f"{odd} row(s) have dates far from the rest of the statement and may be misread.")
    if dropped:
        res.warnings.append(f"{dropped} row(s) were dropped because they had no usable date or amount.")

    for r in rows:
        r.setdefault("flags", [])
        r.setdefault("ref", None)
        r.setdefault("time", None)
        if res.ocr_used:
            # Tesseract commonly reads the letter I in UPI as a 1 or l
            r["description"] = re.sub(r"\bUP[1lI]\b", "UPI", r["description"])
        r["merchant"] = extract_merchant(r["description"])
        r["merchant_key"] = merchant_key(r["merchant"])
        if res.ocr_used and "Read with OCR. Check amount" not in r["flags"] and res.parser != "ai":
            r["flags"].append("Read with OCR. Check amount")

    res.rows = rows
    if res.source_type == "gpay":
        res.account_name = "Google Pay"
    else:
        bank, last4 = _guess_account(_preamble(ex))
        res.account_name = (bank + " account") if bank else None
        res.account_last4 = last4
    if not rows:
        res.warnings.append("No transactions were found in this file.")
    return res
