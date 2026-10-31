"""Explicit import rules and manually confirmed non-personal cash-flow groups."""
import re
from datetime import date

from .txns import now, get_category

def description_key(text):
    return re.sub(r"\s+", " ", (text or "").strip().casefold())[:500]

def matching_exclusion(db, row):
    if not row["merchant_key"] or not row["description"]:
        return False
    return bool(db.execute(
        "SELECT 1 FROM import_exclusions WHERE user_id=? AND account_id=? AND merchant_key=? "
        "AND description_key=? AND amount_minor=? AND direction=?",
        (row["user_id"], row["account_id"], row["merchant_key"], description_key(row["description"]),
         row["amount_minor"], row["direction"])).fetchone())

def save_exclusion(db, user_id, txn_id):
    row = db.execute("SELECT * FROM transactions WHERE user_id=? AND id=? AND status!='staged'",
                     (user_id, txn_id)).fetchone()
    if not row:
        raise LookupError("Transaction not found.")
    if len(row["merchant_key"] or "") < 3 or len(description_key(row["description"])) < 5:
        raise ValueError("An exclusion needs a recognizable merchant and description.")
    db.execute(
        "INSERT OR IGNORE INTO import_exclusions"
        "(user_id,account_id,merchant_key,description_key,amount_minor,direction) VALUES(?,?,?,?,?,?)",
        (user_id, row["account_id"], row["merchant_key"], description_key(row["description"]),
         row["amount_minor"], row["direction"]))
    return row

def remember(db, user_id, row, category_id, txn_type):
    if len(row["merchant_key"] or "") < 3:
        raise ValueError("A remembered pattern needs a recognizable merchant.")
    if not get_category(db, user_id, category_id):
        raise ValueError("Unknown category.")
    db.execute(
        "INSERT INTO classification_rules(user_id,account_id,merchant_key,direction,category_id,type) "
        "VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,account_id,merchant_key,direction) DO UPDATE SET "
        "category_id=excluded.category_id,type=excluded.type",
        (user_id, row["account_id"], row["merchant_key"], row["direction"], category_id, txn_type))

def classify_import(db, user_id, ids):
    """Only apply a user-approved exact merchant/account/direction rule to non-duplicate rows."""
    n = 0
    for tid in ids:
        row = db.execute("SELECT * FROM transactions WHERE id=? AND user_id=?", (tid, user_id)).fetchone()
        if not row or row["dup_status"] not in (None, "cleared") or row["status"] != "pending":
            continue
        if row["transfer_pair_id"] or row["type"] == "transfer":
            continue
        rule = db.execute(
            "SELECT category_id,type FROM classification_rules WHERE user_id=? AND account_id=? "
            "AND merchant_key=? AND direction=?",
            (user_id, row["account_id"], row["merchant_key"], row["direction"])).fetchone()
        if rule:
            db.execute("UPDATE transactions SET category_id=?, type=?, status='categorized', reviewed_at=? "
                       "WHERE id=?", (rule["category_id"], rule["type"], now(), tid))
            n += 1
    return n

def rules(db, user_id):
    return {
        "exclusions": [dict(r) for r in db.execute(
            "SELECT e.*, a.name account_name FROM import_exclusions e JOIN accounts a ON a.id=e.account_id "
            "WHERE e.user_id=? ORDER BY e.id DESC", (user_id,))],
        "classifications": [dict(r) for r in db.execute(
            "SELECT r.*,a.name account_name,c.name category_name FROM classification_rules r "
            "JOIN accounts a ON a.id=r.account_id JOIN categories c ON c.id=r.category_id "
            "WHERE r.user_id=? ORDER BY r.id DESC", (user_id,))]
    }

def unlink(db, user_id, group_id, txn_id):
    member = db.execute(
        "SELECT m.* FROM transaction_group_members m JOIN transaction_groups g ON g.id=m.group_id "
        "WHERE g.user_id=? AND m.group_id=? AND m.txn_id=?", (user_id, group_id, txn_id)).fetchone()
    if not member:
        raise LookupError("Group membership not found.")
    db.execute("DELETE FROM transaction_group_members WHERE group_id=? AND txn_id=?", (group_id, txn_id))
    db.execute("UPDATE transactions SET type=?,category_id=?,status=?,reviewed_at=? WHERE id=?",
               (member["original_type"],member["original_category_id"],member["original_status"],
                member["original_reviewed_at"], txn_id))

def add_members(db, user_id, group_id, ids):
    if not db.execute("SELECT 1 FROM transaction_groups WHERE id=? AND user_id=?", (group_id,user_id)).fetchone():
        raise LookupError("Group not found.")
    ids = list(dict.fromkeys(ids))
    if not ids or len(ids) > 100:
        raise ValueError("Choose between 1 and 100 transactions.")
    rows = db.execute(f"SELECT * FROM transactions WHERE user_id=? AND status!='staged' "
                      f"AND id IN ({','.join('?' for _ in ids)})", [user_id, *ids]).fetchall()
    if len(rows) != len(ids):
        raise ValueError("Some transactions don't belong to this account.")
    from . import refunds
    for row in rows:
        refunds.ensure_not_refund_linked(db,user_id,row)
        if db.execute("SELECT 1 FROM transaction_group_members WHERE txn_id=?", (row["id"],)).fetchone():
            raise ValueError("A transaction can belong to only one group.")
        if db.execute("SELECT 1 FROM splits WHERE txn_id=?", (row["id"],)).fetchone():
            raise ValueError("Remove split categories before grouping a transaction.")
        if row["dup_status"] == "suspected":
            raise ValueError("Resolve suspected duplicates before linking.")
    transfers = db.execute("SELECT id FROM categories WHERE user_id=? AND name='Transfers'",(user_id,)).fetchone()
    for row in rows:
        db.execute("INSERT INTO transaction_group_members "
                   "(group_id,txn_id,original_type,original_category_id,original_status,original_reviewed_at) "
                   "VALUES(?,?,?,?,?,?)",
                   (group_id,row["id"],row["type"],row["category_id"],row["status"],row["reviewed_at"]))
        db.execute("UPDATE transactions SET type='transfer',category_id=?,status='categorized',reviewed_at=? WHERE id=?",
                   (transfers["id"] if transfers else None,now(),row["id"]))
    return len(rows)

def list_groups(db, user_id):
    groups = [dict(g) for g in db.execute(
        "SELECT * FROM transaction_groups WHERE user_id=? ORDER BY id DESC",(user_id,))]
    for g in groups:
        items=[dict(r) for r in db.execute(
            "SELECT t.id,t.date,t.amount_minor,t.direction,t.merchant,t.description,t.account_id,a.name account_name "
            "FROM transaction_group_members m JOIN transactions t ON t.id=m.txn_id "
            "JOIN accounts a ON a.id=t.account_id WHERE m.group_id=? ORDER BY t.date DESC,t.id DESC",(g["id"],))]
        g["items"]=items
        g["received_minor"]=sum(t["amount_minor"] for t in items if t["direction"]=="credit")
        g["paid_minor"]=sum(t["amount_minor"] for t in items if t["direction"]=="debit")
        g["unsettled_minor"]=g["received_minor"]-g["paid_minor"]
    return groups

def suggestions(db, user_id, txn_id):
    row=db.execute("SELECT * FROM transactions WHERE user_id=? AND id=? AND status!='staged'",
                   (user_id,txn_id)).fetchone()
    if not row:
        raise LookupError("Transaction not found.")
    candidates=db.execute(
        "SELECT t.id,t.date,t.amount_minor,t.direction,t.merchant,t.description,a.name account_name "
        "FROM transactions t JOIN accounts a ON a.id=t.account_id "
        "WHERE t.user_id=? AND t.id!=? AND t.direction!=? AND t.status!='staged' "
        "AND (t.dup_status IS NULL OR t.dup_status='cleared') "
        "AND NOT EXISTS(SELECT 1 FROM transaction_group_members m WHERE m.txn_id=t.id) "
        "ORDER BY ABS(julianday(t.date)-julianday(?)),t.id DESC LIMIT 100",
        (user_id,txn_id,row["direction"],row["date"])).fetchall()
    key=(row["merchant_key"] or "").casefold()
    terms=set(re.findall(r"[a-z0-9]{4,}",(row["description"] or "").casefold()))
    found=[]
    for r in candidates:
        days=abs((date.fromisoformat(row["date"])-date.fromisoformat(r["date"])).days)
        if days>90:
            continue
        overlap=bool(key and key in (r["merchant"] or "").casefold()) or bool(
            terms & set(re.findall(r"[a-z0-9]{4,}",(r["description"] or "").casefold())))
        same_amount=row["amount_minor"]==r["amount_minor"]
        if not same_amount and not overlap:
            continue
        score=(40 if same_amount else 0)+(25 if overlap else 0)+max(0,30-days)
        found.append({**dict(r),"score":score,"reason":"Same amount" if same_amount else "Related description"})
    return sorted(found,key=lambda x:-x["score"])[:12]
