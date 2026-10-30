"""Credit-card spend summaries and conservative repayment confirmation."""
from datetime import date, timedelta
import re
import json

ACTIVE = "t.status IN ('pending','categorized','skipped') AND t.removed_at IS NULL AND (t.dup_status IS NULL OR t.dup_status='cleared')"
PAYMENT = re.compile(r"(?i)(credit.?card|card.?bill|cc.?payment|supermoney|card repayment|autopay)")

def overview(db, uid, month=None):
    month = month if month and re.fullmatch(r"\d{4}-\d{2}",month) else date.today().strftime("%Y-%m")
    cards = [dict(x) for x in db.execute("SELECT * FROM accounts WHERE user_id=? AND type='card' ORDER BY name",(uid,))]
    bank_rows = [dict(x) for x in db.execute(
        f"SELECT t.* FROM transactions t JOIN accounts a ON a.id=t.account_id "
        f"WHERE t.user_id=? AND a.type!='card' AND t.direction='debit' AND {ACTIVE} "
        "AND t.transfer_pair_id IS NULL ORDER BY t.date DESC LIMIT 2000",(uid,))]
    results=[]
    for card in cards:
        transactions=[dict(t) for t in db.execute(
            f"SELECT t.* FROM transactions t WHERE t.user_id=? AND t.account_id=? AND {ACTIVE} "
            "AND substr(t.date,1,7)=? ORDER BY t.date DESC", (uid,card["id"],month))]
        spent=sum(t["amount_minor"] for t in transactions if t["direction"]=="debit" and t["type"]=="expense")
        spent-=sum(t["amount_minor"] for t in transactions if t["direction"]=="credit" and t["type"]=="expense")
        spent=max(0,spent)
        limit=card["card_monthly_limit_minor"] or 0
        statements=[dict(st) for st in db.execute(
            "SELECT id,card_meta,date_from,date_to FROM statements WHERE user_id=? AND account_id=? "
            "AND status='imported' AND source_type='card' ORDER BY date_to DESC,id DESC LIMIT 24",
            (uid,card["id"]))]
        billing=[]
        for st in statements:
            try: meta=json.loads(st["card_meta"] or "{}")
            except (ValueError,TypeError): meta={}
            if meta.get("due_date") or meta.get("amount_due_minor") is not None:
                billing.append({"statement_id":st["id"],"statement_date":meta.get("statement_date"),
                    "billing_start":meta.get("billing_start"),"billing_end":meta.get("billing_end"),
                    "due_date":meta.get("due_date"),"amount_due_minor":meta.get("amount_due_minor"),
                    "minimum_due_minor":meta.get("minimum_due_minor")})
        suggestions=[]
        # Card credits are repayment evidence. Never infer repayments from equal
        # amounts alone: require a card credit and a bank-side payment clue.
        credits=[dict(t) for t in db.execute(
            f"SELECT t.* FROM transactions t WHERE t.user_id=? AND t.account_id=? "
            f"AND t.direction='credit' AND t.type='transfer' AND {ACTIVE} AND t.transfer_pair_id IS NULL",
            (uid,card["id"]))]
        for bank in bank_rows:
            if not PAYMENT.search(bank["description"]+" "+bank["merchant"]):
                continue
            matches=[c for c in credits if c["amount_minor"]==bank["amount_minor"]
                     and abs((date.fromisoformat(c["date"])-date.fromisoformat(bank["date"])).days)<=3]
            if len(matches)==1:
                c=matches[0]
                if sum(1 for other in bank_rows if other["amount_minor"]==bank["amount_minor"]
                       and abs((date.fromisoformat(other["date"])-date.fromisoformat(c["date"])).days)<=3
                       and PAYMENT.search(other["description"]+" "+other["merchant"]))!=1:
                    continue
                suggestions.append({"bank_txn_id":bank["id"],"card_txn_id":c["id"],"date":bank["date"],
                                    "amount_minor":bank["amount_minor"],"description":bank["description"][:130]})
        # Balance is calculated over the complete imported card history, not just
        # the selected month. Card debits increase what is owed, and card credits
        # (repayments/refunds) decrease it, even when classified as transfers.
        # Opening outstanding must represent the balance before imported history.
        movements = db.execute(
            f"SELECT t.direction,t.amount_minor FROM transactions t WHERE t.user_id=? "
            f"AND t.account_id=? AND {ACTIVE}",
            (uid,card["id"])).fetchall()
        outstanding = max(0, (card["card_opening_outstanding_minor"] or 0) +
                          sum(x["amount_minor"] if x["direction"]=="debit" else -x["amount_minor"]
                              for x in movements))
        credit_limit = card["card_credit_limit_minor"] or 0
        available = max(0, credit_limit - outstanding) if credit_limit else None
        utilization = round(100*outstanding/credit_limit,1) if credit_limit else None
        results.append({"id":card["id"],"name":card["name"],"last4":card["last4"],
                        "monthly_limit_minor":limit,"month":month,"spent_minor":spent,
                        "remaining_minor":max(0,limit-spent) if limit else None,
                        "usage_percent":round(100*spent/limit,1) if limit else None,
                        "credit_limit_minor":credit_limit,"opening_outstanding_minor":card["card_opening_outstanding_minor"] or 0,
                        "outstanding_minor":outstanding,"available_credit_minor":available,
                        "utilization_percent":utilization,
                        "repayment_suggestions":suggestions[:40],"billing_statements":billing})
    return {"month":month,"cards":results}


def confirm_repayment(db,uid,card_id,bank_id):
    card=db.execute("SELECT * FROM accounts WHERE id=? AND user_id=? AND type='card'",(card_id,uid)).fetchone()
    if not card: raise LookupError("Credit card not found")
    data=overview(db,uid)
    item=next((x for c in data["cards"] if c["id"]==card_id for x in c["repayment_suggestions"]
               if x["bank_txn_id"]==bank_id),None)
    if item is None: raise ValueError("No unambiguous bank/card repayment match; review manually.")
    card_txn=item["card_txn_id"]
    transfer_cat=db.execute("SELECT id FROM categories WHERE user_id=? AND name='Transfers'",(uid,)).fetchone()
    cid=transfer_cat["id"] if transfer_cat else None
    for tid,partner in ((bank_id,card_txn),(card_txn,bank_id)):
        db.execute("UPDATE transactions SET type='transfer',category_id=?,status='categorized',"
                   "reviewed_at=datetime('now'),transfer_pair_id=? WHERE id=? AND user_id=?",
                   (cid,partner,tid,uid))
    return {"bank_txn_id":bank_id,"card_txn_id":card_txn,"status":"transfer"}
