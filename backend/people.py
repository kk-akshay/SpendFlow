"""User-confirmed person ledgers for UPI repayments; raw bank amounts never change."""
import re
from . import txns

UPI_RE = re.compile(r"(?i)(?<![\w.@])([a-z0-9][a-z0-9._-]{1,80}@[a-z][a-z0-9.-]{1,50})(?![\w.])")
ROLES={"lent":"debit","repaid":"credit","borrowed":"credit","paid_back":"debit","other":None}

def upi_ids(text):
    return sorted({x.lower() for x in UPI_RE.findall(text or "")})

def own(db,uid,pid):
    row=db.execute("SELECT * FROM people WHERE id=? AND user_id=?",(pid,uid)).fetchone()
    if not row: raise LookupError("Person not found.")
    return row

def overview(db,uid):
    persons=[dict(x) for x in db.execute("SELECT * FROM people WHERE user_id=? ORDER BY lower(name),id",(uid,))]
    for p in persons:
        p["upi_ids"]=[dict(r) for r in db.execute("SELECT id,upi_id FROM people_upi WHERE person_id=? ORDER BY upi_id",(p["id"],))]
        p["transactions"]=[dict(r) for r in db.execute(
          "SELECT t.id,t.date,t.amount_minor,t.direction,t.description,t.merchant,t.account_id,a.name AS account_name,l.role FROM people_transactions l "
          "JOIN transactions t ON t.id=l.txn_id JOIN accounts a ON a.id=t.account_id "
          "WHERE l.person_id=? AND l.user_id=? AND t.removed_at IS NULL ORDER BY t.date DESC,t.id DESC",(p["id"],uid))]
        p["lent_minor"]=sum(t["amount_minor"] for t in p["transactions"] if t["role"]=="lent")
        p["repaid_minor"]=sum(t["amount_minor"] for t in p["transactions"] if t["role"]=="repaid")
        p["borrowed_minor"]=sum(t["amount_minor"] for t in p["transactions"] if t["role"]=="borrowed")
        p["paid_back_minor"]=sum(t["amount_minor"] for t in p["transactions"] if t["role"]=="paid_back")
        p["owed_to_me_minor"]=p["lent_minor"]-p["repaid_minor"]
        p["i_owe_minor"]=p["borrowed_minor"]-p["paid_back_minor"]
    return persons

def suggestions(db,uid,tid):
    row=db.execute("SELECT * FROM transactions WHERE id=? AND user_id=? AND status!='staged' AND removed_at IS NULL",(tid,uid)).fetchone()
    if not row: raise LookupError("Transaction not found.")
    ids=upi_ids(row["description"])
    known=[]
    for x in ids:
        known += [dict(p) for p in db.execute("SELECT p.id,p.name FROM people p JOIN people_upi u ON u.person_id=p.id WHERE p.user_id=? AND u.upi_id=?",(uid,x))]
    names=[dict(p) for p in db.execute("SELECT id,name FROM people WHERE user_id=? AND lower(name) LIKE ? LIMIT 10",(uid,"%"+(row["merchant"] or "").strip().lower()[:40]+"%"))] if len((row["merchant"] or "").strip())>=3 else []
    return {"txn_id":tid,"merchant":row["merchant"],"upi_ids":ids,"exact_people":known,"similar_names":names}

def link(db,uid,pid,tid,role):
    own(db,uid,pid)
    if role not in ROLES: raise ValueError("Invalid loan role.")
    t=db.execute("SELECT * FROM transactions WHERE user_id=? AND id=? AND status!='staged' AND removed_at IS NULL",(uid,tid)).fetchone()
    if not t: raise LookupError("Transaction not found.")
    if ROLES[role] and ROLES[role]!=t["direction"]: raise ValueError("This role does not match the transaction direction.")
    if db.execute("SELECT 1 FROM people_transactions WHERE txn_id=?",(tid,)).fetchone(): raise ValueError("Already linked to a person. Unlink first.")
    for table in ("transaction_group_members","flow_group_members"):
        if db.execute(f"SELECT 1 FROM {table} WHERE txn_id=?",(tid,)).fetchone(): raise ValueError("Unlink existing cash-flow group first.")
    if t["dup_status"]=="suspected" or db.execute("SELECT 1 FROM splits WHERE txn_id=?",(tid,)).fetchone(): raise ValueError("Resolve suspected duplicates and splits before linking.")
    db.execute("INSERT INTO people_transactions(txn_id,user_id,person_id,role,original_type,original_category_id,original_status,original_reviewed_at,original_skipped_at) VALUES(?,?,?,?,?,?,?,?,?)",
               (tid,uid,pid,role,t["type"],t["category_id"],t["status"],t["reviewed_at"],t["skipped_at"]))
    if role!="other":
        db.execute("UPDATE transactions SET type='transfer',category_id=NULL,status='categorized',reviewed_at=? WHERE id=?",(txns.now(),tid))

def unlink(db,uid,tid):
    r=db.execute("SELECT * FROM people_transactions WHERE txn_id=? AND user_id=?",(tid,uid)).fetchone()
    if not r: raise LookupError("Person link not found.")
    db.execute("UPDATE transactions SET type=?,category_id=?,status=?,reviewed_at=?,skipped_at=? WHERE id=?",
               (r["original_type"],r["original_category_id"],r["original_status"],r["original_reviewed_at"],r["original_skipped_at"],tid))
    db.execute("DELETE FROM people_transactions WHERE txn_id=? AND user_id=?",(tid,uid))

def candidates(db,uid,pid):
    p=own(db,uid,pid)
    aliases={a["upi_id"] for a in db.execute("SELECT upi_id FROM people_upi WHERE person_id=?",(pid,))}
    rows=db.execute("SELECT t.id,t.date,t.direction,t.amount_minor,t.merchant,t.description,a.name AS account_name "
                    "FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE t.user_id=? AND t.status!='staged' "
                    "AND t.removed_at IS NULL AND (t.dup_status IS NULL OR t.dup_status='cleared') "
                    "AND NOT EXISTS(SELECT 1 FROM people_transactions l WHERE l.txn_id=t.id) "
                    "AND NOT EXISTS(SELECT 1 FROM transaction_group_members l WHERE l.txn_id=t.id) "
                    "AND NOT EXISTS(SELECT 1 FROM flow_group_members l WHERE l.txn_id=t.id) "
                    "ORDER BY t.date DESC,t.id DESC LIMIT 1500",(uid,)).fetchall()
    matches=[]
    for t in rows:
        ids=set(upi_ids(t["description"]))
        exact=bool(aliases & ids)
        name_match=bool(len(p["name"].strip())>=4 and p["name"].strip().casefold() in (t["merchant"] or "").casefold())
        if exact or name_match:
            matches.append({**dict(t),"reason":"Matching UPI ID" if exact else "Similar name (confirm identity)"})
    return matches[:100]
