"""User-confirmed refund classification, safe linking and deterministic suggestions.

Original bank amounts/dates are immutable here. A refund is stored as an expense
credit plus is_refund=1, so legacy transaction type CHECK constraints still work.
"""
from __future__ import annotations

import re
from datetime import date
from difflib import SequenceMatcher

ACTIVE = "status IN ('pending','categorized','skipped') AND removed_at IS NULL AND (dup_status IS NULL OR dup_status='cleared')"


def _owned(db, user_id, txn_id):
    return db.execute(
        "SELECT * FROM transactions WHERE id=? AND user_id=? AND " + ACTIVE,
        (txn_id, user_id),
    ).fetchone()


def linked_total(db, user_id, expense_id, exclude_id=0):
    return db.execute(
        "SELECT COALESCE(SUM(amount_minor),0) FROM transactions "
        "WHERE user_id=? AND refund_of_id=? AND is_refund=1 AND id!=? AND " + ACTIVE,
        (user_id, expense_id, exclude_id),
    ).fetchone()[0]


def validate_amount_change(db, user_id, txn, amount_minor, direction):
    """Protect existing links when someone edits an original or a refund."""
    if txn["refund_of_id"]:
        if direction != "credit":
            raise ValueError("Unlink the refund before changing its direction.")
        original = _owned(db, user_id, txn["refund_of_id"])
        if original and linked_total(db, user_id, original["id"], txn["id"]) + amount_minor > original["amount_minor"]:
            raise ValueError("Linked refunds cannot exceed the original expense.")
    if txn["direction"] == "debit":
        refunded = linked_total(db, user_id, txn["id"])
        if refunded and (direction != "debit" or amount_minor < refunded):
            raise ValueError("This purchase has refunds. Keep its amount above the refunded total, or unlink them first.")


def link(db, user_id, refund_id, purchase_id):
    if refund_id == purchase_id:
        raise ValueError("A refund cannot link to itself.")
    # Lock the parent in PostgreSQL to serialize competing partial refund links.
    lock = " FOR UPDATE" if hasattr(db, "_conn") else ""
    purchase = db.execute(
        "SELECT * FROM transactions WHERE id=? AND user_id=? AND " + ACTIVE + lock,
        (purchase_id, user_id),
    ).fetchone()
    refund = _owned(db, user_id, refund_id)
    if not refund or refund["direction"] != "credit" or not refund["is_refund"] or refund["type"] != "expense":
        raise ValueError("First classify an incoming transaction as Refund/Reversal.")
    if (not purchase or purchase["direction"] != "debit" or purchase["type"] != "expense"
            or purchase["is_refund"] or purchase["account_id"] is None):
        raise ValueError("Choose an active original expense belonging to your account.")
    for tid in (refund_id, purchase_id):
        if db.execute(
            "SELECT 1 FROM (SELECT txn_id FROM transaction_group_members UNION ALL "
            "SELECT txn_id FROM flow_group_members UNION ALL SELECT txn_id FROM people_transactions) x "
            "WHERE x.txn_id=?", (tid,),
        ).fetchone():
            raise ValueError("Unlink loan or transfer groups before linking a refund.")
    already = linked_total(db, user_id, purchase_id, refund_id)
    if already + refund["amount_minor"] > purchase["amount_minor"]:
        raise ValueError("This refund exceeds the remaining refundable purchase amount.")
    # A single FK on the refund prevents the same credit being linked twice.
    db.execute(
        "UPDATE transactions SET refund_of_id=?,category_id=? WHERE id=? AND user_id=?",
        (purchase_id, purchase["category_id"], refund_id, user_id),
    )
    db.commit()
    return {"refund_id": refund_id, "expense_id": purchase_id,
            "remaining_minor": purchase["amount_minor"] - already - refund["amount_minor"]}


def unlink(db, user_id, refund_id):
    refund = _owned(db, user_id, refund_id)
    if not refund or not refund["is_refund"]:
        raise LookupError("Refund not found.")
    db.execute("UPDATE transactions SET refund_of_id=NULL WHERE id=? AND user_id=?", (refund_id, user_id))
    db.commit()
    return {"refund_id": refund_id, "unlinked": True}


def candidates(db, user_id, refund_id, q="", from_date=None, to_date=None, amount_minor=None):
    refund = _owned(db, user_id, refund_id)
    if not refund or refund["direction"] != "credit":
        raise LookupError("Incoming transaction not found.")
    where = ["p.user_id=?", "p.direction='debit'", "p.type='expense'", "p.is_refund=0",
             "p.id!=?", "p." + ACTIVE.replace("status", "status").replace("removed_at", "removed_at")]
    params = [user_id, refund_id]
    if from_date:
        date.fromisoformat(from_date)
        where.append("p.date>=?")
        params.append(from_date)
    if to_date:
        date.fromisoformat(to_date)
        where.append("p.date<=?")
        params.append(to_date)
    if amount_minor is not None:
        if amount_minor <= 0:
            raise ValueError("Search amount must be positive.")
        where.append("p.amount_minor=?")
        params.append(amount_minor)
    if q:
        key = "%" + q.strip()[:100] + "%"
        where.append("(p.merchant LIKE ? OR p.description LIKE ?)")
        params.extend((key, key))
    # Keep the candidate list bounded, never enumerate an entire user's ledger.
    rows = db.execute(
        "SELECT p.id,p.date,p.amount_minor,p.merchant,p.merchant_key,p.description,"
        "COALESCE((SELECT SUM(r.amount_minor) FROM transactions r WHERE r.user_id=p.user_id "
        "AND r.refund_of_id=p.id AND r.is_refund=1 AND " + "r." + ACTIVE.replace("status", "status").replace("removed_at", "removed_at") + "),0) AS refunded_minor "
        "FROM transactions p WHERE " + " AND ".join(where) +
        " ORDER BY p.date DESC,p.id DESC LIMIT 600", params,
    ).fetchall()
    token = lambda s: set(re.findall(r"[a-z]{3,}", (s or "").lower()))
    words = token(refund["merchant"] + " " + refund["description"])
    today = date.fromisoformat(refund["date"])
    found = []
    for row in rows:
        d = dict(row)
        remaining = d["amount_minor"] - d["refunded_minor"]
        if remaining < refund["amount_minor"]:
            continue
        days = (today - date.fromisoformat(d["date"])).days
        shared = words & token(d["merchant"] + " " + d["description"])
        score = 0
        reasons = []
        if refund["merchant_key"] and refund["merchant_key"] == d["merchant_key"]:
            score += 60
            reasons.append("same merchant")
        elif refund["merchant_key"] and d["merchant_key"] and SequenceMatcher(None, refund["merchant_key"], d["merchant_key"]).ratio() > 0.78:
            score += 25
            reasons.append("similar merchant")
        if shared:
            score += min(30, len(shared) * 10)
            reasons.append("matching description")
        if d["amount_minor"] == refund["amount_minor"]:
            score += 18
            reasons.append("same amount")
        if 0 <= days <= 14:
            score += 18
            reasons.append("within two weeks")
        elif 0 <= days <= 90:
            score += 8
            reasons.append("within three months")
        elif days < 0:
            score -= 15
        if d["refunded_minor"]:
            reasons.append("previous partial refund")
        found.append({**d, "remaining_minor": remaining, "score": score,
                      "reason": ", ".join(reasons) or "possible expense"})
    found.sort(key=lambda r: (-r["score"], abs((today - date.fromisoformat(r["date"])).days), -r["id"]))
    return found[:40 if q or from_date or to_date or amount_minor is not None else 8]
