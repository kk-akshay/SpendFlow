"""Staging imported rows, duplicate detection, own-account transfer detection, and commit."""
from __future__ import annotations

import json
from collections import defaultdict
import re
from datetime import date, timedelta

from .merchants import SELF_TRANSFER, extract_merchant, merchant_key
from .statement_parser import ParseResult
from .txns import now
from . import ledger, payee_names

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
    # One batched DB operation rather than hundreds of network round trips.
    # Keep insert_staged_row() for manual preview-row edits (which need lastrowid).
    remembered_names = payee_names.all_rules(db, user_id)
    params = [
        (user_id, account_id, sid, r["date"], r.get("time"), r["amount_minor"],
         r["direction"], ("transfer" if res.source_type == "card" and "Credit card repayment" in r.get("flags", []) else ("expense" if res.source_type == "card" else ("income" if r["direction"] == "credit" else "expense"))),
         *payee_names.renamed_fields(r, remembered_names),
         r.get("description", ""), r.get("ref"), r.get("balance_minor"), json.dumps(r.get("flags", [])))
        for r in res.rows
    ]
    db.executemany(
        "INSERT INTO transactions(user_id,account_id,statement_id,date,time,amount_minor,direction,type,"
        "merchant,merchant_key,description,ref,balance_minor,status,flags) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'staged',?)", params)
    mark_duplicates(db, user_id, sid)
    refresh_statement_meta(db, sid)
    return sid


def insert_staged_row(db, user_id: int, account_id: int, statement_id: int, r: dict) -> int:
    account = db.execute("SELECT type FROM accounts WHERE id=? AND user_id=?", (account_id,user_id)).fetchone()
    ttype = ("transfer" if account and account["type"] == "card" and "Credit card repayment" in r.get("flags", []) else ("expense" if account and account["type"] == "card" else ("income" if r["direction"] == "credit" else "expense")))
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
    """Find duplicate staged rows using one candidate read, not one query per row.

    Preserve the old +/- one-day comparison and first-25-candidates priority.
    This matters especially when PostgreSQL is reached over the network.
    """
    counts = {"exact": 0, "suspected": 0}
    db.execute("UPDATE transactions SET dup_status=NULL, dup_of=NULL WHERE statement_id=? AND status='staged' "
               "AND dup_status IN ('exact','suspected')", (statement_id,))
    rows = db.execute("SELECT * FROM transactions WHERE statement_id=? AND status='staged' AND dup_status IS NULL",
                      (statement_id,)).fetchall()
    if not rows:
        return counts

    start = (min(date.fromisoformat(r["date"]) for r in rows) - timedelta(days=1)).isoformat()
    end = (max(date.fromisoformat(r["date"]) for r in rows) + timedelta(days=1)).isoformat()
    candidates = db.execute(
        f"SELECT * FROM transactions WHERE user_id=? AND date BETWEEN ? AND ? "
        f"AND status IN {STAGED_OR_LIVE} AND removed_at IS NULL "
        f"AND (statement_id IS NULL OR statement_id!=?) "
        f"AND (dup_status IS NULL OR dup_status='cleared') ORDER BY id",
        (user_id, start, end, statement_id)).fetchall()
    by_amount = defaultdict(list)
    for c in candidates:
        by_amount[(c["amount_minor"], c["direction"])].append(c)

    for row in rows:
        d = date.fromisoformat(row["date"])
        lo, hi = (d - timedelta(days=1)).isoformat(), (d + timedelta(days=1)).isoformat()
        best, best_id, matched = None, None, 0
        for c in by_amount.get((row["amount_minor"], row["direction"]), ()):
            if not lo <= c["date"] <= hi:
                continue
            matched += 1
            if matched > 25:
                break
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
        "SELECT t.*, a.name AS account_name, a.type AS account_type FROM transactions t JOIN accounts a ON a.id=t.account_id "
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
    """Detect eligible account transfers with a single candidate lookup.

    Keep reciprocal matching: two same-amount payments aren't necessarily
    a transfer unless each transaction has exactly one eligible counterpart.
    """
    if not ids:
        return 0
    marks = ",".join("?" * len(ids))
    rows = db.execute(
        f"SELECT t.*, a.name AS account_name FROM transactions t JOIN accounts a ON a.id=t.account_id "
        f"WHERE t.id IN ({marks}) AND t.status='pending' "
        f"AND (t.dup_status IS NULL OR t.dup_status='cleared')", ids).fetchall()
    if not rows:
        return 0
    start = (min(date.fromisoformat(r["date"]) for r in rows) - timedelta(days=3)).isoformat()
    end = (max(date.fromisoformat(r["date"]) for r in rows) + timedelta(days=3)).isoformat()
    possible = db.execute(
        "SELECT t.*, a.name AS account_name FROM transactions t JOIN accounts a ON a.id=t.account_id "
        "WHERE t.user_id=? AND t.date BETWEEN ? AND ? "
        "AND t.status IN ('pending','categorized','skipped') "
        "AND (t.dup_status IS NULL OR t.dup_status='cleared') "
        "AND t.transfer_pair_id IS NULL AND t.removed_at IS NULL "
        "AND (t.status!='categorized' OR t.type='transfer')",
        (user_id, start, end)).fetchall()
    by_amount = defaultdict(list)
    for c in possible:
        by_amount[(c["amount_minor"], c["direction"])].append(c)
    paired = set()

    def candidates_for(t):
        day = date.fromisoformat(t["date"])
        lo, hi = (day - timedelta(days=3)).isoformat(), (day + timedelta(days=3)).isoformat()
        opposite = "credit" if t["direction"] == "debit" else "debit"
        return [c for c in by_amount.get((t["amount_minor"], opposite), ())
                if c["id"] != t["id"] and c["id"] not in paired
                and c["account_id"] != t["account_id"] and lo <= c["date"] <= hi]

    n = 0
    for r in rows:
        if r["transfer_pair_id"] or r["id"] in paired:
            continue
        if SELF_TRANSFER.search(r["description"]):
            db.execute("UPDATE transactions SET type='transfer' WHERE id=?", (r["id"],))
            _add_flag(db, r["id"], "Looks like a transfer between your own accounts")
            n += 1
        cands = candidates_for(r)
        # Card bill payments require corroborating narration and an explicit
        # confirmation through the credit-card repayment matcher.
        if r["account_type"] == "card" or any(c["account_type"] == "card" for c in cands):
            continue
        if len(cands) != 1:
            continue
        c = cands[0]
        back = candidates_for(c)
        if len(back) != 1 or back[0]["id"] != r["id"]:
            continue
        for me, other in ((r, c), (c, r)):
            db.execute("UPDATE transactions SET type='transfer', transfer_pair_id=? WHERE id=?",
                       (other["id"], me["id"]))
            kind = "credit" if other["direction"] == "credit" else "debit"
            _add_flag(db, me["id"],
                      f"Matches a {kind} of {other['amount_minor'] / 100:,.2f} in {other['account_name']} on {other['date']}. "
                      f"Looks like a transfer between your own accounts")
        paired.update((r["id"], c["id"]))
        n += 1
    return n

def commit_statement(db, user_id: int, statement_id: int) -> dict:
    st = db.execute("SELECT * FROM statements WHERE id=? AND user_id=? AND status='preview'",
                    (statement_id, user_id)).fetchone()
    if not st:
        raise LookupError("Statement not found, or it was already confirmed.")
    mark_duplicates(db, user_id, statement_id)
    dropped = db.execute("DELETE FROM transactions WHERE statement_id=? AND status='staged' AND dup_status='exact'",
                         (statement_id,)).rowcount
    db.execute(
        "UPDATE transactions SET dup_status=NULL, dup_of=NULL WHERE statement_id=? AND dup_status='suspected' "
        "AND (dup_of IS NULL OR dup_of NOT IN (SELECT id FROM transactions))", (statement_id,))
    staged = db.execute("SELECT * FROM transactions WHERE statement_id=? AND status='staged'",
                        (statement_id,)).fetchall()
    ids = [r["id"] for r in staged]
    db.execute("UPDATE transactions SET status='pending' WHERE statement_id=? AND status='staged'", (statement_id,))

    # Load rules once. The old implementation issued two/three remote SELECTs
    # for every imported transaction, which was very slow for long statements.
    exclude_rules = {
        (r["account_id"], r["merchant_key"], r["direction"], r["amount_minor"]): r["id"]
        for r in db.execute("SELECT id,account_id,merchant_key,direction,amount_minor FROM exclusion_rules "
                            "WHERE user_id=?", (user_id,))
    }
    exact_exclusions = {
        (r["account_id"], r["merchant_key"], r["description_key"], r["amount_minor"], r["direction"])
        for r in db.execute("SELECT account_id,merchant_key,description_key,amount_minor,direction "
                            "FROM import_exclusions WHERE user_id=?", (user_id,))
    }
    classifications = {
        (r["account_id"], r["merchant_key"], r["direction"]): r
        for r in db.execute("SELECT account_id,merchant_key,direction,category_id,type "
                            "FROM classification_rules WHERE user_id=?", (user_id,))
    }
    excluded = auto_classified = 0
    timestamp = now()
    for t in staged:
        rule_id = exclude_rules.get((t["account_id"], t["merchant_key"], t["direction"], t["amount_minor"]))
        exact_key = (t["account_id"], t["merchant_key"], ledger.description_key(t["description"]),
                     t["amount_minor"], t["direction"])
        matches_exact = bool(t["merchant_key"] and t["description"] and exact_key in exact_exclusions)
        if rule_id is not None or matches_exact:
            db.execute("UPDATE transactions SET removed_at=?,excluded_rule_id=? WHERE id=?",
                       (timestamp, rule_id, t["id"]))
            excluded += 1
            continue
        learned = classifications.get((t["account_id"], t["merchant_key"], t["direction"]))
        if learned and t["dup_status"] != "suspected":
            db.execute("UPDATE transactions SET category_id=?,type=?,status='categorized',reviewed_at=? WHERE id=?",
                       (learned["category_id"], learned["type"], timestamp, t["id"]))
            auto_classified += 1

    transfers = detect_transfers(db, user_id, ids)
    suspected = db.execute(
        "SELECT COUNT(*) FROM transactions WHERE statement_id=? AND dup_status='suspected'",
        (statement_id,)).fetchone()[0]
    db.execute("UPDATE statements SET status='imported' WHERE id=?", (statement_id,))
    refresh_statement_meta(db, statement_id)
    db.commit()
    return {"imported": len(ids) - excluded, "already_imported": dropped,
            "suspected_duplicates": suspected, "transfers_detected": transfers,
            "excluded": excluded, "auto_classified": auto_classified}

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
