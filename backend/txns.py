"""Transaction logic: serialisation, smart suggestions, categorising (with splits/undo), search, bulk edits."""
from __future__ import annotations

import difflib
import json
import re
from datetime import datetime, timezone

from .merchants import keyword_category

# A transaction "counts" once imported, unless it is an unresolved suspected duplicate.
DUP_OK = "(t.dup_status IS NULL OR t.dup_status='cleared')"
ACTIVE = f"t.status IN ('pending','categorized','skipped') AND t.removed_at IS NULL AND {DUP_OK}"

SELECT_TXN = """
SELECT t.*, a.name AS account_name, c.name AS category_name, c.color AS category_color, c.kind AS category_kind,
       (SELECT COUNT(*) FROM splits s WHERE s.txn_id = t.id) AS split_count
FROM transactions t
JOIN accounts a ON a.id = t.account_id
LEFT JOIN categories c ON c.id = t.category_id
"""

FREQS = ("weekly", "monthly", "yearly")
TYPES = ("income", "expense", "transfer")
SNAP_FIELDS = ("category_id", "note", "recurring", "recurring_freq", "type", "status",
               "reviewed_at", "skipped_at", "transfer_pair_id", "flags", "dup_status")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def now_precise() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def serialize(row) -> dict:
    d = dict(row)
    d["flags"] = json.loads(d.get("flags") or "[]")
    d["recurring"] = bool(d.get("recurring"))
    d["is_split"] = (d.pop("split_count", 0) or 0) > 0
    d.pop("user_id", None)
    d.pop("created_at", None)
    return d


def get_txn(db, user_id: int, txn_id: int) -> dict | None:
    row = db.execute(SELECT_TXN + " WHERE t.id=? AND t.user_id=?", (txn_id, user_id)).fetchone()
    if not row:
        return None
    d = serialize(row)
    d["splits"] = [dict(r) for r in db.execute(
        "SELECT s.id, s.category_id, c.name AS category_name, c.color AS category_color, s.amount_minor, s.note "
        "FROM splits s JOIN categories c ON c.id=s.category_id WHERE s.txn_id=? ORDER BY s.id", (txn_id,))]
    return d


def get_category(db, user_id: int, category_id) -> dict | None:
    if category_id is None:
        return None
    r = db.execute("SELECT * FROM categories WHERE id=? AND user_id=?", (category_id, user_id)).fetchone()
    return dict(r) if r else None


def category_by_name(db, user_id: int, name: str) -> dict | None:
    r = db.execute("SELECT * FROM categories WHERE user_id=? AND name=?", (user_id, name)).fetchone()
    return dict(r) if r else None


def derive_type(kind: str) -> str:
    return {"transfer": "transfer", "income": "income"}.get(kind, "expense")


# ---------------------------------------------------------------- suggestions

def suggest(db, user_id: int, t: dict) -> dict | None:
    """Best guess at a category for a transaction, with a human-readable reason."""
    if t["type"] == "transfer":
        c = category_by_name(db, user_id, "Transfers")
        if c:
            why = next((f for f in t["flags"] if "transfer" in f.lower()), "Looks like a transfer between your own accounts")
            return {"category_id": c["id"], "source": "transfer", "reason": why}

    key = t.get("merchant_key") or ""
    if key:
        rule = db.execute("SELECT category_id FROM classification_rules WHERE user_id=? AND merchant_key=? AND direction=?", (user_id, key, t["direction"])).fetchone()
        if rule:
            return {"category_id": rule["category_id"], "source": "saved_rule", "reason": "Your saved classification"}
    name = t.get("merchant") or "this merchant"
    if key:
        saved = db.execute("SELECT category_id FROM classification_rules WHERE user_id=? AND account_id=? AND merchant_key=? AND direction=?",
                           (user_id,t["account_id"],key,t["direction"])).fetchone()
        if saved:
            return {"category_id":saved["category_id"],"source":"remembered","reason":"You chose to remember this classification"}
        r = db.execute(
            "SELECT mr.category_id, mr.hits, c.name FROM merchant_rules mr JOIN categories c ON c.id=mr.category_id "
            "WHERE mr.user_id=? AND mr.merchant_key=?", (user_id, key)).fetchone()
        if r:
            n = r["hits"]
            reason = (f"You've put {n} “{name}” transactions in {r['name']}" if n > 1
                      else f"You put “{name}” in {r['name']} before")
            return {"category_id": r["category_id"], "source": "history", "reason": reason}
        rules = db.execute(
            "SELECT mr.merchant_key, mr.category_id, c.name FROM merchant_rules mr "
            "JOIN categories c ON c.id=mr.category_id WHERE mr.user_id=? LIMIT 800", (user_id,)).fetchall()
        if rules:
            match = difflib.get_close_matches(key, [x["merchant_key"] for x in rules], n=1, cutoff=0.82)
            if match:
                r = next(x for x in rules if x["merchant_key"] == match[0])
                return {"category_id": r["category_id"], "source": "similar",
                        "reason": f"Similar to “{match[0]}”, which you put in {r['name']}"}

    kw = keyword_category(f"{t.get('merchant', '')} {t.get('description', '')}", t["direction"])
    if kw:
        c = category_by_name(db, user_id, kw[0])
        if c:
            return {"category_id": c["id"], "source": "keyword", "reason": f"“{kw[1]}” usually means {kw[0]}"}
    return None


# ---------------------------------------------------------------- categorising

def snapshot(db, txn_id: int) -> dict:
    row = db.execute(f"SELECT id, {','.join(SNAP_FIELDS)} FROM transactions WHERE id=?", (txn_id,)).fetchone()
    s = dict(row)
    s["splits"] = [dict(r) for r in db.execute(
        "SELECT category_id, amount_minor, note FROM splits WHERE txn_id=?", (txn_id,))]
    return s


def restore(db, user_id: int, snaps: list[dict]) -> int:
    n = 0
    for s in snaps[:500]:
        if not isinstance(s, dict) or not isinstance(s.get("id"), int):
            continue
        if not db.execute("SELECT 1 FROM transactions WHERE id=? AND user_id=?", (s["id"], user_id)).fetchone():
            continue
        cat = s.get("category_id")
        if cat is not None and not get_category(db, user_id, cat):
            cat = None
        status = s.get("status") if s.get("status") in ("pending", "categorized", "skipped") else "pending"
        ttype = s.get("type") if s.get("type") in TYPES else "expense"
        freq = s.get("recurring_freq") if s.get("recurring_freq") in FREQS else None
        pair = s.get("transfer_pair_id")
        if pair is not None and not db.execute("SELECT 1 FROM transactions WHERE id=? AND user_id=?", (pair, user_id)).fetchone():
            pair = None
        flags = s.get("flags") if isinstance(s.get("flags"), str) else "[]"
        db.execute(
            "UPDATE transactions SET category_id=?, note=?, recurring=?, recurring_freq=?, type=?, status=?, "
            "reviewed_at=?, skipped_at=?, transfer_pair_id=?, flags=? WHERE id=?",
            (cat, (s.get("note") or None) and str(s["note"])[:500], 1 if s.get("recurring") else 0, freq, ttype,
             status, s.get("reviewed_at"), s.get("skipped_at"), pair, flags, s["id"]))
        db.execute("DELETE FROM splits WHERE txn_id=?", (s["id"],))
        for sp in s.get("splits") or []:
            if isinstance(sp.get("amount_minor"), int) and sp["amount_minor"] > 0 and get_category(db, user_id, sp.get("category_id")):
                db.execute("INSERT INTO splits(txn_id,category_id,amount_minor,note) VALUES(?,?,?,?)",
                           (s["id"], sp["category_id"], sp["amount_minor"], sp.get("note")))
        n += 1
    return n


def _learn(db, user_id: int, merchant_key: str, category_id: int) -> None:
    if len(merchant_key) < 3:
        return
    db.execute(
        "INSERT INTO merchant_rules(user_id,merchant_key,category_id,hits,updated_at) VALUES(?,?,?,1,?) "
        "ON CONFLICT(user_id,merchant_key) DO UPDATE SET "
        "hits = CASE WHEN category_id=excluded.category_id THEN hits+1 ELSE 1 END, "
        "category_id=excluded.category_id, updated_at=excluded.updated_at",
        (user_id, merchant_key, category_id, now()))


def _strip_transfer_flags(flags_json: str) -> str:
    flags = [f for f in json.loads(flags_json or "[]") if "transfer" not in f.lower()]
    return json.dumps(flags)


def apply_category(db, user_id: int, txn_id: int, p: dict) -> dict:
    """Categorise one transaction. Returns the new state plus undo snapshots."""
    t = db.execute("SELECT * FROM transactions WHERE id=? AND user_id=? AND status!='staged'", (txn_id, user_id)).fetchone()
    if not t:
        raise LookupError("Transaction not found")
    if db.execute("SELECT 1 FROM transaction_group_members WHERE txn_id=?", (txn_id,)).fetchone():
        raise ValueError("Unlink this transaction from its group before changing its category.")
    snaps = [snapshot(db, txn_id)]

    splits = p.get("splits") or None
    cat = None
    if splits:
        if not isinstance(splits, list) or len(splits) < 2:
            raise ValueError("A split needs at least two parts.")
        total, clean, kinds = 0, [], []
        for sp in splits:
            c = get_category(db, user_id, sp.get("category_id"))
            amt = sp.get("amount_minor")
            if not c or not isinstance(amt, int) or amt <= 0:
                raise ValueError("Each part of a split needs a category and an amount above zero.")
            if c["kind"] == "transfer":
                raise ValueError("A split can't include the Transfers category.")
            total += amt
            kinds.append(c["kind"])
            clean.append((c["id"], amt, (sp.get("note") or None) and str(sp["note"])[:200]))
        if total != t["amount_minor"]:
            raise ValueError("The parts of a split must add up to the full amount.")
        derived = "income" if all(k == "income" for k in kinds) else "expense"
        category_id = None
    else:
        cat = get_category(db, user_id, p.get("category_id"))
        if not cat:
            raise ValueError("Please choose a category.")
        derived = derive_type(cat["kind"])
        category_id = cat["id"]
        clean = []

    ttype = p.get("type") if p.get("type") in TYPES else derived
    note = (str(p["note"]).strip()[:500] or None) if "note" in p and p["note"] is not None else t["note"]
    recurring = bool(p["recurring"]) if "recurring" in p else bool(t["recurring"])
    freq = (p.get("recurring_freq") if p.get("recurring_freq") in FREQS else (t["recurring_freq"] or "monthly")) if recurring else None
    ts = now()

    db.execute(
        "UPDATE transactions SET category_id=?, note=?, recurring=?, recurring_freq=?, type=?, status='categorized', "
        "reviewed_at=?, skipped_at=NULL WHERE id=?",
        (category_id, note, 1 if recurring else 0, freq, ttype, ts, txn_id))
    db.execute("DELETE FROM splits WHERE txn_id=?", (txn_id,))
    for cid, amt, snote in clean:
        db.execute("INSERT INTO splits(txn_id,category_id,amount_minor,note) VALUES(?,?,?,?)", (txn_id, cid, amt, snote))

    # Linked transfer partner
    partner_confirmed = False
    pair = t["transfer_pair_id"]
    if pair:
        partner = db.execute("SELECT * FROM transactions WHERE id=? AND user_id=?", (pair, user_id)).fetchone()
        if partner:
            if ttype == "transfer":
                if partner["status"] == "pending":
                    snaps.append(snapshot(db, partner["id"]))
                    tc = category_by_name(db, user_id, "Transfers")
                    db.execute("UPDATE transactions SET category_id=?, type='transfer', status='categorized', reviewed_at=? WHERE id=?",
                               (tc["id"] if tc else None, ts, partner["id"]))
                    partner_confirmed = True
            else:
                snaps.append(snapshot(db, partner["id"]))
                if partner["status"] in ("pending", "skipped"):
                    db.execute("UPDATE transactions SET type=?, transfer_pair_id=NULL, flags=? WHERE id=?",
                               ("income" if partner["direction"] == "credit" else "expense",
                                _strip_transfer_flags(partner["flags"]), partner["id"]))
                else:
                    db.execute("UPDATE transactions SET transfer_pair_id=NULL WHERE id=?", (partner["id"],))
                db.execute("UPDATE transactions SET transfer_pair_id=NULL, flags=? WHERE id=?",
                           (_strip_transfer_flags(t["flags"]), txn_id))

    if p.get("remember") and cat and t["merchant_key"]:
        from . import ledger
        ledger.remember(db, user_id, t, cat["id"], ttype)

    applied = 0
    if p.get("apply_similar") and cat and t["merchant_key"]:
        rows = db.execute(
            "SELECT id FROM transactions WHERE user_id=? AND merchant_key=? AND direction=? AND status='pending' "
            "AND id!=? AND transfer_pair_id IS NULL AND removed_at IS NULL AND (dup_status IS NULL OR dup_status='cleared')",
            (user_id, t["merchant_key"], t["direction"], txn_id)).fetchall()
        for r in rows:
            snaps.append(snapshot(db, r["id"]))
            db.execute("UPDATE transactions SET category_id=?, type=?, status='categorized', reviewed_at=? WHERE id=?",
                       (cat["id"], derived, ts, r["id"]))
            applied += 1
    db.commit()
    return {"txn": get_txn(db, user_id, txn_id), "undo": snaps, "applied_similar": applied,
            "partner_confirmed": partner_confirmed}


def skip_txn(db, user_id: int, txn_id: int) -> dict:
    t = db.execute("SELECT id FROM transactions WHERE id=? AND user_id=? AND status IN ('pending','skipped')", (txn_id, user_id)).fetchone()
    if not t:
        raise LookupError("Transaction not found")
    snap = snapshot(db, txn_id)
    db.execute("UPDATE transactions SET status='skipped', skipped_at=? WHERE id=?", (now_precise(), txn_id))
    db.commit()
    return {"undo": [snap]}


# ---------------------------------------------------------------- review queue

def progress(db, user_id: int) -> dict:
    r = db.execute(
        f"SELECT COUNT(*) total, SUM(t.status='categorized') done, SUM(t.status='skipped') skipped, "
        f"SUM(t.status='pending') pending FROM transactions t WHERE t.user_id=? AND {ACTIVE}", (user_id,)).fetchone()
    return {"total": r["total"] or 0, "reviewed": r["done"] or 0, "skipped": r["skipped"] or 0, "pending": r["pending"] or 0}


def _build_item(db, user_id: int, row) -> dict:
    t = serialize(row)
    similar = 0
    if t["merchant_key"]:
        similar = db.execute(
            "SELECT COUNT(*) FROM transactions WHERE user_id=? AND merchant_key=? AND direction=? AND status='pending' "
            "AND id!=? AND transfer_pair_id IS NULL AND removed_at IS NULL AND (dup_status IS NULL OR dup_status='cleared')",
            (user_id, t["merchant_key"], t["direction"], t["id"])).fetchone()[0]
    pair = None
    if t["transfer_pair_id"]:
        p = db.execute("SELECT t.date, t.amount_minor, a.name AS account_name FROM transactions t JOIN accounts a ON a.id=t.account_id "
                       "WHERE t.id=?", (t["transfer_pair_id"],)).fetchone()
        pair = dict(p) if p else None
    return {"txn": t, "suggestion": suggest(db, user_id, t), "similar_count": similar, "pair": pair}


def next_item(db, user_id: int, scope: str = "pending", order: str = "desc") -> dict | None:
    if scope == "skipped":
        sort, status = "t.skipped_at, t.id", "skipped"
    else:
        sort, status = "t.date, COALESCE(t.time,''), t.id", "pending"
    direction = "ASC" if order == "asc" else "DESC"
    sort = ", ".join(piece.strip() + " " + direction for piece in sort.split(", ") )
    row = db.execute(
        SELECT_TXN + f" WHERE t.user_id=? AND t.status=? AND {DUP_OK} ORDER BY {sort} LIMIT 1", (user_id, status)).fetchone()
    return _build_item(db, user_id, row) if row else None


def item_for(db, user_id: int, txn_id: int) -> dict | None:
    row = db.execute(SELECT_TXN + f" WHERE t.id=? AND t.user_id=? AND t.status IN ('pending','skipped') AND t.removed_at IS NULL AND {DUP_OK}",
                     (txn_id, user_id)).fetchone()
    return _build_item(db, user_id, row) if row else None


# ---------------------------------------------------------------- search & bulk

def search(db, user_id: int, f: dict) -> dict:
    where = ["t.user_id=?", "t.status!='staged'"]
    if not f.get("include_removed"):
        where.append("t.removed_at IS NULL")
    args: list = [user_id]
    if f.get("dup") == "suspected":
        where.append("t.dup_status='suspected'")
    elif not f.get("include_dups"):
        where.append(DUP_OK)
    if f.get("q"):
        q = f["q"].strip()
        like = f"%{q}%"
        parts = ["t.merchant LIKE ?", "t.description LIKE ?", "t.note LIKE ?", "c.name LIKE ?"]
        a = [like, like, like, like]
        try:
            minor = round(float(q.replace(",", "")) * 100)
            parts.append("t.amount_minor=?")
            a.append(minor)
        except ValueError:
            pass
        where.append("(" + " OR ".join(parts) + ")")
        args += a
    cat = f.get("category")
    if cat == "uncategorized":
        where.append("t.status IN ('pending','skipped')")
    elif cat:
        where.append("(t.category_id=? OR EXISTS(SELECT 1 FROM splits s WHERE s.txn_id=t.id AND s.category_id=?))")
        args += [int(cat), int(cat)]
    if f.get("account"):
        where.append("t.account_id=?")
        args.append(int(f["account"]))
    if f.get("status") in ("pending", "categorized", "skipped"):
        where.append("t.status=?")
        args.append(f["status"])
    if f.get("type") in TYPES:
        where.append("t.type=?")
        args.append(f["type"])
    if f.get("recurring"):
        where.append("t.recurring=1")
    if f.get("from"):
        where.append("t.date>=?")
        args.append(f["from"])
    if f.get("to"):
        where.append("t.date<=?")
        args.append(f["to"])
    if f.get("min") not in (None, ""):
        where.append("t.amount_minor>=?")
        args.append(round(float(f["min"]) * 100))
    if f.get("max") not in (None, ""):
        where.append("t.amount_minor<=?")
        args.append(round(float(f["max"]) * 100))
    order = {"date_asc": "t.date ASC, t.id ASC", "amount_desc": "t.amount_minor DESC, t.id DESC",
             "amount_asc": "t.amount_minor ASC, t.id ASC"}.get(f.get("sort"), "t.date DESC, COALESCE(t.time,'') DESC, t.id DESC")
    limit = max(1, min(int(f.get("limit") or 50), 200))
    offset = (max(1, int(f.get("page") or 1)) - 1) * limit
    base = " FROM transactions t JOIN accounts a ON a.id=t.account_id LEFT JOIN categories c ON c.id=t.category_id WHERE " + " AND ".join(where)
    agg = db.execute(
        "SELECT COUNT(*) n, "
        "COALESCE(SUM(CASE WHEN t.type='income' AND t.direction='credit' THEN t.amount_minor END),0) money_in, "
        "COALESCE(SUM(CASE WHEN t.type='expense' AND t.direction='debit' THEN t.amount_minor END),0) money_out" + base, args).fetchone()
    rows = db.execute(SELECT_TXN + " WHERE " + " AND ".join(where) + f" ORDER BY {order} LIMIT ? OFFSET ?", args + [limit, offset]).fetchall()
    return {"items": [serialize(r) for r in rows], "total": agg["n"], "money_in": agg["money_in"],
            "money_out": agg["money_out"], "page": offset // limit + 1, "pages": max(1, -(-agg["n"] // limit))}


def bulk(db, user_id: int, ids: list[int], action: str, p: dict) -> dict:
    ids = [i for i in ids if isinstance(i, int)][:1000]
    if not ids:
        raise ValueError("No transactions selected.")
    own = [r["id"] for r in db.execute(
        f"SELECT id FROM transactions WHERE user_id=? AND status!='staged' AND id IN ({','.join('?' * len(ids))})", [user_id] + ids)]
    snaps: list[dict] = []
    if action == "categorize":
        if not get_category(db, user_id, p.get("category_id")):
            raise ValueError("Please choose a category.")
        for i in own:
            snaps += apply_category(db, user_id, i, {"category_id": p["category_id"]})["undo"]
    elif action == "pending":
        for i in own:
            snaps.append(snapshot(db, i))
            db.execute("DELETE FROM splits WHERE txn_id=?", (i,))
            db.execute("UPDATE transactions SET category_id=NULL, status='pending', reviewed_at=NULL, skipped_at=NULL, "
                       "type=CASE WHEN transfer_pair_id IS NOT NULL THEN 'transfer' WHEN direction='credit' THEN 'income' ELSE 'expense' END "
                       "WHERE id=?", (i,))
    elif action == "type":
        if p.get("type") not in TYPES:
            raise ValueError("Unknown type.")
        for i in own:
            snaps.append(snapshot(db, i))
            db.execute("UPDATE transactions SET type=? WHERE id=?", (p["type"], i))
    elif action == "delete":
        if own:
            marks = ",".join("?" * len(own))
            db.execute(f"UPDATE transactions SET removed_at=? WHERE id IN ({marks})", [now(), *own])
        db.commit()
        return {"changed": len(own), "undo": []}
    else:
        raise ValueError("Unknown action.")
    db.commit()
    return {"changed": len(own), "undo": snaps}


def clean_note(s) -> str | None:
    if s is None:
        return None
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s[:500] or None
