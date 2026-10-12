"""Google Pay "Transaction statement" parser.

Each transaction is a short block:
    01Jan, 2024  Paid to SWIGGY                ₹250
    09:30 PM     UPI Transaction ID: 400112233445
                 Paid by HDFC Bank 1234
"""
from __future__ import annotations

import re

from .extract import Page
from .parse_common import group_lines, parse_time, to_minor

_DATE = re.compile(r"^\s*(\d{1,2})\s*([A-Za-z]{3,9})\.?,?\s*(\d{4})\b")
_RUPEE = re.compile(r"(?:₹|Rs\.?|INR)\s?([\d,]+(?:\.\d{1,2})?)")
_TRAILING_NUM = re.compile(r"([\d,]+(?:\.\d{1,2})?)\s*$")
_UPI_ID = re.compile(r"UPI\s*Transaction\s*ID\s*:?\s*(\d{6,})", re.I)
_PAID_BY = re.compile(r"^(?:Paid\s+by|Paid\s+from|Credited\s+to|Debited\s+from)\s+(.+)$", re.I)

DEBIT_PREFIX = re.compile(r"(?i)^(paid to|sent to|money sent to|payment to|self transfer to|transfer to)\b")
CREDIT_PREFIX = re.compile(r"(?i)^(received from|money received from|refund from|transfer from)\b")


def looks_like_gpay(text: str) -> bool:
    low = text.lower()
    return "upi transaction id" in low or ("google pay" in low and ("paid to" in low or "received from" in low))


def parse_gpay(pages: list[Page]) -> tuple[list[dict], list[str]]:
    from .parse_common import month_number

    rows: list[dict] = []
    cur: dict | None = None
    skipped_failed = 0

    def finish():
        nonlocal cur, skipped_failed
        if not cur:
            return
        c, cur = cur, None
        if c["failed"]:
            skipped_failed += 1
            return
        if not c["amount"]:
            return
        desc = c["desc"].strip()
        direction = c["direction"]
        flags = []
        if direction is None:
            low = desc.lower()
            if "received" in low or "refund" in low:
                direction = "credit"
            elif "paid" in low or "sent" in low:
                direction = "debit"
            else:
                direction = "debit"
                flags.append("Couldn't tell if this was money in or out. Assumed money out")
        extras = []
        if c["ref"]:
            extras.append(f"UPI ID {c['ref']}")
        if c["paid_by"]:
            extras.append(c["paid_by"])
        full = desc + (" | " + " | ".join(extras) if extras else "")
        rows.append({
            "date": c["date"], "time": c["time"], "description": full,
            "amount_minor": c["amount"], "direction": direction, "balance_minor": None,
            "ref": c["ref"], "flags": flags,
        })

    for pno, page in enumerate(pages):
        for line in group_lines(page, pno):
            text = line.text
            m = _DATE.match(text)
            mo = month_number(m.group(2)) if m else None
            if m and mo:
                finish()
                from .parse_common import _mk
                iso = _mk(int(m.group(3)), mo, int(m.group(1)))
                if not iso:
                    continue
                rest = text[m.end():].strip(" ,")
                looks_txn = bool(re.match(r"(?i)^(paid|received|sent|self|money|payment|refund|transfer|credited|debited)\b", rest)) or bool(_RUPEE.search(rest))
                if not looks_txn:
                    continue   # e.g. the "01 August - 31 August" statement period line
                amount = None
                rm = list(_RUPEE.finditer(rest))
                if rm:
                    amount = to_minor(rm[-1].group(1))
                    rest = (rest[: rm[-1].start()] + rest[rm[-1].end():]).strip()
                else:
                    tm = _TRAILING_NUM.search(rest)
                    if tm and re.search(r"\d", tm.group(1)):
                        try:
                            amount = to_minor(tm.group(1))
                            rest = rest[: tm.start()].strip()
                        except Exception:
                            amount = None
                t = parse_time(rest)
                if t:
                    rest = re.sub(r"\b\d{1,2}:\d{2}\s?(?:AM|PM|am|pm)?\b", "", rest).strip()
                cur = {
                    "date": iso, "time": t, "desc": rest, "amount": amount, "ref": None, "paid_by": None,
                    "direction": "debit" if DEBIT_PREFIX.match(rest) else "credit" if CREDIT_PREFIX.match(rest) else None,
                    "failed": bool(re.search(r"(?i)\b(failed|declined)\b", rest)),
                }
            elif cur is not None:
                if re.search(r"(?i)\b(failed|declined)\b", text):
                    cur["failed"] = True
                if (um := _UPI_ID.search(text)):
                    cur["ref"] = um.group(1)
                    t = parse_time(text)
                    if t and not cur["time"]:
                        cur["time"] = t
                elif (pm := _PAID_BY.match(text.strip())):
                    cur["paid_by"] = f"{text.strip()}"
                elif (t := parse_time(text)) and not cur["time"] and len(text) < 20:
                    cur["time"] = t
                elif re.search(r"(?i)(page \d|google pay|statement|transaction statement)", text):
                    continue
                elif cur["desc"].lower().rstrip().endswith(("to", "from")) or len(cur["desc"]) < 4:
                    cur["desc"] = (cur["desc"] + " " + text).strip()
                    if cur["direction"] is None:
                        cur["direction"] = "debit" if DEBIT_PREFIX.match(cur["desc"]) else "credit" if CREDIT_PREFIX.match(cur["desc"]) else None
        # blocks never span pages cleanly in GPay exports, but keep state across pages anyway
    finish()
    warnings = []
    if skipped_failed:
        warnings.append(f"Skipped {skipped_failed} failed or declined transaction(s).")
    return rows, warnings
