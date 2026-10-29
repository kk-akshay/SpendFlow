"""Staging imported rows, duplicate detection, own-account transfer detection, and commit."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

from .merchants import SELF_TRANSFER, extract_merchant, merchant_key
from .statement_parser import ParseResult
from .txns import now
from . import ledger

STAGED_OR_LIVE = "('pending','categorized','skipped','staged')"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _related(a: str, b: str) -> bool:
    return bool(a and b and (a == b or a in b or b in a))


def create_statement(db, user_id: int, account_id: int, filename: str, stored_path: str, sha: str, mime: str,
                     res: ParseResult) -> int:
    cur = db.execute(
        "INSERT INTO statements(user_id,account_id,filename,stored_path,sha256,mime,source_type,parser,status,warnings) "
        "VALUES(?,?,?,?,?,?,?,?,'preview',?)",
        (user_id, account_id, filename, stored_path, sha, mime, res.source_type, res.parser, json.dumps(res.warnings)))
    sid = cur.lastrowid
    for r in res.rows:
        insert_staged_row(db, user_id, account_id, sid, r)
    mark_duplicates(db, user_id, sid)
    refresh_statement_meta(db, sid)
    return sid


def insert_staged_row(db, user_id: int, account_id: int, statement_id: int, r: dict) -> int:
    ttype = "income" if r["direction"] == "credit" else "expense"
    cur = db.execute(
        "INSERT INTO transactions(user_id,account_id,statement_id,date,time,amount_minor,direction,type,merchant,"
        "merchant_key,description,ref,balance_minor,status,flags) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'staged',?)",
        (user_id, account_id, statement_id, r["date"], r.get("time"), r["amount_minor"], r["direction"], ttype,
         r.get("merchant", ""), r.get("merchant_key", ""), r.get("description", ""), r.get("ref"),
         r.get("balance_minor"), json.dumps(r.get("flags", []))))
    return cur.lastrowid


def refresh_statement_meta(db, statement_id: int) -> None:
    r = db.execute("SELECT MIN(date) a, MAX(date) b, COUNT(*) n FROM transactions WHERE statement_id=?", (statement_id,)).fetchone()
    db.execute("UPDATE statements SET date_from=?, date_to=?, txn_count=? WHERE id=?", (r["a"], r["b"], r["n"], statement_id))


def _classify(row, c) -> str | None:
    same_acct = row["account_id"] == c["account_id"]
    if row["ref"] and c["ref"] and row["ref"] == c["ref"]:
        return "exact" if same_acct else "suspected"
    if same_acct and row["date"] == c["date"] and _norm(row["description"]) == _norm(c["description"]):
        if row["balance_minor"] is not None and c["balance_minor"] is not None:
            return "exact" if row["balance_minor"] == c["balance_minor"] else None
        return "suspected"
    if not same_acct and _related(row["merchant_key"], c["merchant_key"]):
        return "suspected"
    return None


def mark_duplicates(db, user_id: int, statement_id: int) -> dict:
    """Compare a statement's staged rows with everything already known. 'exact' rows are dropped at commit;
    'suspected' rows are kept but held out of totals until the user decides."""
    counts = {"exact": 0, "suspected": 0}
    # Recompute from scratch, but respect rows the user explicitly marked "import anyway" ('cleared').
    db.execute("UPDATE transactions SET dup_status=NULL, dup_of=NULL WHERE statement_id=? AND status='staged' "
               "AND dup_status IN ('exact','suspected')", (statement_id,))
    rows = db.execute("SELECT * FROM transactions WHERE statement_id=? AND status='staged' AND dup_status IS NULL",
                      (statement_id,)).fetchall()
    for row in rows:
        d = date.fromisoformat(row["date"])
        lo, hi = (d - timedelta(days=1)).isoformat(), (d + timedelta(days=1)).isoformat()
        cands = db.execute(
            f"SELECT * FROM transactions WHERE user_id=? AND amount_minor=? AND direction=? AND date BETWEEN ? AND ? "
            f"AND status IN {STAGED_OR_LIVE} AND removed_at IS NULL AND (statement_id IS NULL OR statement_id!=?) "
            f"AND (dup_status IS NULL OR dup_status='cleared') ORDER BY id LIMIT 25",
            (user_id, row["amount_minor"], row["direction"], lo, hi, statement_id)).fetchall()
        best, best_id = None, None
        for c in cands:
            k = _classify(row, c)
            if k == "exact":
                best, best_id = "exact", c["id"]
                break
            if k == "suspected" and best is None:
                best, best_id = "suspected", c["id"]
        if best:
            db.execute("UPDATE transactions SET dup_status=?, dup_of=? WHERE id=?", (best, best_id, row["id"]))
            counts[best] += 1
    return counts


def _candidates(db, user_id: int, r) -> list:
    d = date.fromisoformat(r["date"])
    return db.execute(
        "SELECT t.*, a.name AS account_name FROM transactions t JOIN accounts a ON a.id=t.account_id "
        "WHERE t.user_id=? AND t.id!=? AND t.account_id!=? AND t.amount_minor=? AND t.direction!=? "
        "AND t.date BETWEEN ? AND ? AND t.status IN ('pending','categorized','skipped') "
        "AND (t.dup_status IS NULL OR t.dup_status='cleared') AND t.transfer_pair_id IS NULL AND t.removed_at IS NULL "
        "AND (t.status!='categorized' OR t.type='transfer')",
        (user_id, r["id"], r["account_id"], r["amount_minor"], r["direction"],
         (d - timedelta(days=3)).isoformat(), (d + timedelta(days=3)).isoformat())).fetchall()


def _add_flag(db, txn_id: int, text: str) -> None:
    row = db.execute("SELECT flags FROM transactions WHERE id=?", (txn_id,)).fetchone()
    flags = json.loads(row["flags"] or "[]")
    if text not in flags:
        flags.append(text)
    db.execute("UPDATE transactions SET flags=? WHERE id=?", (json.dumps(flags), txn_id))


def detect_transfers(db, user_id: int, ids: list[int]) -> int:
    """Mark money moving between the user's own accounts as transfers so it never counts as income/expense."""
    if not ids:
        return 0
    marks = ",".join("?" * len(ids))
    rows = db.execute(
        f"SELECT t.*, a.name AS account_name FROM transactions t JOIN accounts a ON a.id=t.account_id "
        f"WHERE t.id IN ({marks}) AND t.status='pending' AND (t.dup_status IS NULL OR t.dup_status='cleared')", ids).fetchall()
    n = 0
    for r in rows:
        fresh = db.execute("SELECT * FROM transactions WHERE id=?", (r["id"],)).fetchone()
        if fresh["transfer_pair_id"]:
            continue
        if SELF_TRANSFER.search(r["description"]):
            db.execute("UPDATE transactions SET type='transfer' WHERE id=?", (r["id"],))
            _add_flag(db, r["id"], "Looks like a transfer between your own accounts")
            n += 1
        cands = _candidates(db, user_id, r)
        if len(cands) != 1:
            continue
        c = cands[0]
        back = _candidates(db, user_id, c)
        if len(back) != 1 or back[0]["id"] != r["id"]:
            continue
        for me, other in ((r, c), (c, r)):
            db.execute("UPDATE transactions SET type='transfer', transfer_pair_id=? WHERE id=?", (other["id"], me["id"]))
            kind = "credit" if other["direction"] == "credit" else "debit"
            _add_flag(db, me["id"],
                      f"Matches a {kind} of {other['amount_minor'] / 100:,.2f} in {other['account_name']} on {other['date']}. "
                      f"Looks like a transfer between your own accounts")
        n += 1
    return n


def commit_statement(db, user_id: int, statement_id: int) -> dict:
    st = db.execute("SELECT * FROM statements WHERE id=? AND user_id=? AND status='preview'", (statement_id, user_id)).fetchone()
    if not st:
        raise LookupError("Statement not found, or it was already confirmed.")
    mark_duplicates(db, user_id, statement_id)  # re-check against anything confirmed since upload
    dropped = db.execute("DELETE FROM transactions WHERE statement_id=? AND status='staged' AND dup_status='exact'", (statement_id,)).rowcount
    # a suspected duplicate whose original has since disappeared is no longer a duplicate
    db.execute(
        "UPDATE transactions SET dup_status=NULL, dup_of=NULL WHERE statement_id=? AND dup_status='suspected' "
        "AND (dup_of IS NULL OR dup_of NOT IN (SELECT id FROM transactions))", (statement_id,))
    ids = [r["id"] for r in db.execute("SELECT id FROM transactions WHERE statement_id=? AND status='staged'", (statement_id,))]
    db.execute("UPDATE transactions SET status='pending' WHERE statement_id=? AND status='staged'", (statement_id,))
    excluded = auto_classified = 0
    for tid in ids:
        t = db.execute("SELECT * FROM transactions WHERE id=?", (tid,)).fetchone()
        rule = db.execute("SELECT id FROM exclusion_rules WHERE user_id=? AND account_id=? AND merchant_key=? AND direction=? AND amount_minor=?", (user_id,t["account_id"],t["merchant_key"],t["direction"],t["amount_minor"])).fetchone()
        if rule or ledger.matching_exclusion(db,t):
            db.execute("UPDATE transactions SET removed_at=?,excluded_rule_id=? WHERE id=?", (now(),rule["id"] if rule else None,tid))
            excluded += 1
            continue
        learned = db.execute("SELECT category_id,type FROM classification_rules WHERE user_id=? AND account_id=? AND merchant_key=? AND direction=?", (user_id,t["account_id"],t["merchant_key"],t["direction"])).fetchone()
        if learned and t["dup_status"] != "suspected":
            db.execute("UPDATE transactions SET category_id=?,type=?,status='categorized',reviewed_at=? WHERE id=?", (learned["category_id"],learned["type"],now(),tid))
            auto_classified += 1
    transfers = detect_transfers(db, user_id, ids)
    suspected = db.execute("SELECT COUNT(*) FROM transactions WHERE statement_id=? AND dup_status='suspected'", (statement_id,)).fetchone()[0]
    db.execute("UPDATE statements SET status='imported' WHERE id=?", (statement_id,))
    refresh_statement_meta(db, statement_id)
    db.commit()
    return {"imported": len(ids) - excluded, "already_imported": dropped, "suspected_duplicates": suspected, "transfers_detected": transfers, "excluded": excluded, "auto_classified": auto_classified}


def duplicate_pairs(db, user_id: int) -> list[dict]:
    """Suspected duplicates with the transaction they resemble."""
    out = []
    rows = db.execute(
        "SELECT t.id, t.date, t.amount_minor, t.direction, t.description, t.merchant, t.dup_of, a.name AS account_name, "
        "s.filename FROM transactions t JOIN accounts a ON a.id=t.account_id LEFT JOIN statements s ON s.id=t.statement_id "
        "WHERE t.user_id=? AND t.dup_status='suspected' AND t.status IN ('pending','categorized','skipped') ORDER BY t.date DESC, t.id DESC",
        (user_id,)).fetchall()
    for r in rows:
        orig = db.execute(
            "SELECT t.id, t.date, t.amount_minor, t.description, t.merchant, a.name AS account_name, s.filename "
            "FROM transactions t JOIN accounts a ON a.id=t.account_id LEFT JOIN statements s ON s.id=t.statement_id "
            "WHERE t.id=? AND t.user_id=?", (r["dup_of"], user_id)).fetchone()
        if not orig:
            db.execute("UPDATE transactions SET dup_status=NULL, dup_of=NULL WHERE id=?", (r["id"],))
            continue
        out.append({"new": dict(r), "original": dict(orig)})
    db.commit()
    return out
