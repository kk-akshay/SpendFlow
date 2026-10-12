"""Dashboard numbers, budgets, recurring bills and plain-language insights.

Rules that keep the numbers honest:
  * Transfers never count as income or expense.
  * Money set aside (category kind 'savings') is shown separately, not as spending.
  * Split transactions count by their parts.
  * A refund (credit filed under an expense category) reduces that category's spending.
  * Suspected duplicates are left out until the user resolves them.
  * Transactions not yet categorised still count as spending, under "Uncategorized".
"""
from __future__ import annotations

import calendar
import statistics
from collections import defaultdict
from datetime import date, timedelta

from .config import CURRENCY
from .txns import ACTIVE, DUP_OK, SELECT_TXN, serialize

LINES = f"""
SELECT t.id, t.date, substr(t.date,1,7) AS month, t.direction, t.type, t.account_id, t.status, t.merchant, t.merchant_key,
       COALESCE(s.category_id, t.category_id) AS category_id,
       COALESCE(s.amount_minor, t.amount_minor) AS amount_minor,
       COALESCE(c.kind,'expense') AS kind
FROM transactions t
LEFT JOIN splits s ON s.txn_id = t.id
LEFT JOIN categories c ON c.id = COALESCE(s.category_id, t.category_id)
WHERE t.user_id = ? AND t.status IN ('pending','categorized','skipped') AND {DUP_OK}
"""

EXP = "CASE WHEN direction='debit' THEN amount_minor ELSE -amount_minor END"
INC = "CASE WHEN direction='credit' THEN amount_minor ELSE -amount_minor END"
SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}


def _group_indian(n: int) -> str:
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


def fmt_money(minor: int) -> str:
    amt = abs(minor) / 100
    sym = SYMBOLS.get(CURRENCY, CURRENCY + " ")
    if amt >= 100:
        n = round(amt)
        body = _group_indian(n) if CURRENCY == "INR" else f"{n:,}"
    else:
        body = f"{amt:,.2f}"
    return f"{'-' if minor < 0 else ''}{sym}{body}"


def add_months(month: str, n: int) -> str:
    y, m = int(month[:4]), int(month[5:7])
    t = y * 12 + (m - 1) + n
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def _add_months_date(d: date, n: int) -> date:
    t = d.year * 12 + (d.month - 1) + n
    y, m = t // 12, t % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def month_list(db, user_id: int) -> list[str]:
    return [r["month"] for r in db.execute(f"SELECT DISTINCT month FROM ({LINES}) ORDER BY month", (user_id,))]


def pick_month(db, user_id: int, month: str | None) -> str | None:
    months = month_list(db, user_id)
    if not months:
        return None
    if month and len(month) == 7:
        return month
    today = date.today().strftime("%Y-%m")
    past = [m for m in months if m <= today]
    return (past or months)[-1]


def monthly_totals(db, user_id: int) -> dict[str, dict]:
    rows = db.execute(
        f"SELECT month, "
        f"SUM(CASE WHEN type='income' THEN {INC} ELSE 0 END) AS income, "
        f"SUM(CASE WHEN type='expense' AND kind!='savings' THEN {EXP} ELSE 0 END) AS expense, "
        f"SUM(CASE WHEN type='expense' AND kind='savings' THEN {EXP} ELSE 0 END) AS saved "
        f"FROM ({LINES}) GROUP BY month", (user_id,)).fetchall()
    return {r["month"]: {"income": r["income"] or 0, "expense": r["expense"] or 0, "saved": r["saved"] or 0} for r in rows}


def category_spend(db, user_id: int, month: str) -> dict:
    rows = db.execute(
        f"SELECT category_id, SUM({EXP}) AS amount FROM ({LINES}) "
        f"WHERE month=? AND type='expense' AND kind!='savings' GROUP BY category_id", (user_id, month)).fetchall()
    return {r["category_id"]: r["amount"] or 0 for r in rows}


# ---------------------------------------------------------------- recurring

def recurring_overview(db, user_id: int) -> dict:
    rows = db.execute(SELECT_TXN + f" WHERE t.user_id=? AND t.recurring=1 AND {ACTIVE} ORDER BY t.date", (user_id,)).fetchall()
    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        groups[r["merchant_key"] or f"id{r['id']}"].append(r)
    today = date.today()
    items = []
    for key, txns in groups.items():
        last = txns[-1]
        freq = last["recurring_freq"] or "monthly"
        d = date.fromisoformat(last["date"])
        nxt = {"weekly": d + timedelta(days=7), "yearly": _add_months_date(d, 12)}.get(freq, _add_months_date(d, 1))
        factor = {"weekly": 52 / 12, "yearly": 1 / 12}.get(freq, 1)
        items.append({
            "key": key, "merchant": last["merchant"] or last["description"][:40], "type": last["type"],
            "amount_minor": last["amount_minor"], "monthly_minor": round(last["amount_minor"] * factor),
            "frequency": freq, "last_date": last["date"], "next_due": nxt.isoformat(),
            "days_until": (nxt - today).days, "count": len(txns),
            "category_id": last["category_id"], "category_name": last["category_name"], "category_color": last["category_color"],
        })
    items.sort(key=lambda i: i["next_due"])
    bills = [i for i in items if i["type"] != "income"]
    return {"items": items, "monthly_total_minor": sum(i["monthly_minor"] for i in bills),
            "count": len(bills)}


def detect_recurring(db, user_id: int) -> list[dict]:
    """Merchants that look recurring (regular gaps, similar amounts) but haven't been marked yet."""
    rows = db.execute(
        f"SELECT t.id, t.date, t.amount_minor, t.merchant, t.merchant_key, t.recurring FROM transactions t "
        f"WHERE t.user_id=? AND {ACTIVE} AND t.type='expense' AND t.direction='debit' AND t.merchant_key!='' ORDER BY t.date",
        (user_id,)).fetchall()
    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        groups[r["merchant_key"]].append(r)
    out = []
    for key, txns in groups.items():
        if any(t["recurring"] for t in txns):
            continue
        dates = [date.fromisoformat(t["date"]) for t in txns]
        gaps = [(b - a).days for a, b in zip(dates, dates[1:]) if (b - a).days > 0]
        amounts = [t["amount_minor"] for t in txns]
        med_amt = statistics.median(amounts)
        if not med_amt or any(abs(a - med_amt) > 0.25 * med_amt for a in amounts):
            continue
        freq = None
        if len(txns) >= 3 and gaps:
            g = statistics.median(gaps)
            if 26 <= g <= 35:
                freq = "monthly"
            elif 6 <= g <= 8:
                freq = "weekly"
        if len(txns) >= 2 and gaps and 350 <= statistics.median(gaps) <= 380:
            freq = "yearly"
        if freq:
            out.append({"key": key, "merchant": txns[-1]["merchant"], "frequency": freq, "count": len(txns),
                        "amount_minor": int(med_amt), "last_date": txns[-1]["date"]})
    out.sort(key=lambda o: -o["amount_minor"])
    return out[:12]


# ---------------------------------------------------------------- budgets

def budgets_status(db, user_id: int, month: str) -> dict:
    spend = category_spend(db, user_id, month)
    total = sum(v for v in spend.values())
    cats = {r["id"]: dict(r) for r in db.execute("SELECT * FROM categories WHERE user_id=?", (user_id,))}
    overall = None
    items = []
    for b in db.execute("SELECT * FROM budgets WHERE user_id=?", (user_id,)):
        if b["category_id"] is None:
            overall = {"id": b["id"], "limit_minor": b["limit_minor"], "spent_minor": total,
                       "pct": round(100 * total / b["limit_minor"])}
        elif b["category_id"] in cats:
            c = cats[b["category_id"]]
            sp = spend.get(c["id"], 0)
            items.append({"id": b["id"], "category_id": c["id"], "category_name": c["name"], "category_color": c["color"],
                          "limit_minor": b["limit_minor"], "spent_minor": sp, "pct": round(100 * sp / b["limit_minor"])})
    items.sort(key=lambda i: -i["pct"])
    return {"overall": overall, "items": items}


# ---------------------------------------------------------------- dashboard

def dashboard(db, user_id: int, month: str | None) -> dict:
    months = month_list(db, user_id)
    if not months:
        return {"empty": True, "months": []}
    month = pick_month(db, user_id, month)
    prev = add_months(month, -1)
    totals = monthly_totals(db, user_id)
    zero = {"income": 0, "expense": 0, "saved": 0}
    cur, prv = totals.get(month, zero), totals.get(prev, zero)

    cats = {r["id"]: dict(r) for r in db.execute("SELECT * FROM categories WHERE user_id=?", (user_id,))}
    cs, ps = category_spend(db, user_id, month), category_spend(db, user_id, prev)
    breakdown = []
    for cid, amt in cs.items():
        if amt <= 0:
            continue
        c = cats.get(cid)
        breakdown.append({"category_id": cid, "name": c["name"] if c else "Uncategorized",
                          "color": c["color"] if c else "#9CA3AF", "amount_minor": amt,
                          "prev_minor": max(ps.get(cid, 0), 0),
                          "pct": round(100 * amt / cur["expense"]) if cur["expense"] > 0 else 0})
    breakdown.sort(key=lambda b: -b["amount_minor"])

    trend = []
    for i in range(5, -1, -1):
        m = add_months(month, -i)
        t = totals.get(m, zero)
        trend.append({"month": m, **t, "net": t["income"] - t["expense"]})

    y, mo = int(month[:4]), int(month[5:7])
    days = calendar.monthrange(y, mo)[1]
    today = date.today()

    def cumulative(m: str) -> list[int | None]:
        rows = db.execute(
            f"SELECT date, SUM({EXP}) AS amt FROM ({LINES}) WHERE month=? AND type='expense' AND kind!='savings' GROUP BY date",
            (user_id, m)).fetchall()
        by_day = {int(r["date"][8:]): r["amt"] or 0 for r in rows}
        n = calendar.monthrange(int(m[:4]), int(m[5:7]))[1]
        run, out = 0, []
        for d in range(1, n + 1):
            run += by_day.get(d, 0)
            out.append(run)
        return out

    cur_cum, prev_cum = cumulative(month), cumulative(prev)
    if month == today.strftime("%Y-%m"):
        cur_cum = [v if d + 1 <= today.day else None for d, v in enumerate(cur_cum)]

    accounts = []
    for r in db.execute(
        f"SELECT a.id, a.name, "
        f"SUM(CASE WHEN x.type='income' THEN ({INC.replace('direction', 'x.direction').replace('amount_minor', 'x.amount_minor')}) ELSE 0 END) AS income, "
        f"SUM(CASE WHEN x.type='expense' THEN ({EXP.replace('direction', 'x.direction').replace('amount_minor', 'x.amount_minor')}) ELSE 0 END) AS expense, "
        f"SUM(CASE WHEN x.type='transfer' AND x.direction='credit' THEN x.amount_minor ELSE 0 END) AS transfer_in, "
        f"SUM(CASE WHEN x.type='transfer' AND x.direction='debit' THEN x.amount_minor ELSE 0 END) AS transfer_out "
        f"FROM accounts a LEFT JOIN ({LINES}) x ON x.account_id=a.id AND x.month=? WHERE a.user_id=? GROUP BY a.id ORDER BY a.name",
        (user_id, month, user_id)):
        accounts.append({k: (r[k] or 0) if k not in ("id", "name") else r[k] for k in r.keys()})

    recent = [serialize(r) for r in db.execute(
        SELECT_TXN + f" WHERE t.user_id=? AND {ACTIVE} ORDER BY t.date DESC, COALESCE(t.time,'') DESC, t.id DESC LIMIT 8", (user_id,))]
    unc = db.execute(
        f"SELECT COUNT(*) n, COALESCE(SUM(t.amount_minor),0) amt FROM transactions t WHERE t.user_id=? AND {ACTIVE} "
        f"AND t.status IN ('pending','skipped') AND t.type!='transfer'", (user_id,)).fetchone()
    unc_month = db.execute(
        f"SELECT COUNT(*) FROM transactions t WHERE t.user_id=? AND {ACTIVE} AND t.status IN ('pending','skipped') "
        f"AND t.type!='transfer' AND substr(t.date,1,7)=?", (user_id, month)).fetchone()[0]
    dup_n = db.execute("SELECT COUNT(*) FROM transactions WHERE user_id=? AND dup_status='suspected' AND status!='staged'", (user_id,)).fetchone()[0]

    budgets = budgets_status(db, user_id, month)
    rec = recurring_overview(db, user_id)
    goals = [dict(g) for g in db.execute("SELECT * FROM goals WHERE user_id=? ORDER BY id", (user_id,))]

    data = {
        "empty": False, "month": month, "months": months, "prev_month": prev,
        "income_minor": cur["income"], "expense_minor": cur["expense"], "net_minor": cur["income"] - cur["expense"],
        "saved_minor": cur["saved"],
        "prev": {"income_minor": prv["income"], "expense_minor": prv["expense"], "net_minor": prv["income"] - prv["expense"]},
        "breakdown": breakdown, "trend": trend,
        "daily": {"days": days, "current": cur_cum, "previous": prev_cum},
        "accounts": accounts, "recent": recent,
        "uncategorized": {"count": unc["n"], "amount_minor": unc["amt"], "count_in_month": unc_month},
        "duplicates": dup_n, "budgets": budgets, "recurring": rec, "goals": goals,
    }
    data["insights"] = insights(db, user_id, data, cats)
    return data


def insights(db, user_id: int, d: dict, cats: dict) -> list[dict]:
    out: list[dict] = []
    month, inc, exp = d["month"], d["income_minor"], d["expense_minor"]
    prev_exp = d["prev"]["expense_minor"]
    mname = date(int(month[:4]), int(month[5:7]), 1).strftime("%B")

    if d["uncategorized"]["count_in_month"]:
        n = d["uncategorized"]["count_in_month"]
        out.append({"tone": "warn", "text": f"{n} transaction{'s' if n != 1 else ''} in {mname} still need a category. "
                                            f"They're counted as “Uncategorized” until you review them."})
    if prev_exp > 0 and exp > 0:
        diff = exp - prev_exp
        pct = round(100 * abs(diff) / prev_exp)
        if pct >= 5:
            out.append({"tone": "warn" if diff > 0 else "good",
                        "text": f"You spent {fmt_money(abs(diff))} {'more' if diff > 0 else 'less'} than last month ({pct}% {'up' if diff > 0 else 'down'})."})
    movers = [(b["amount_minor"] - b["prev_minor"], b) for b in d["breakdown"] if b["prev_minor"] > 0]
    if movers:
        diff, b = max(movers, key=lambda x: x[0])
        if diff > 0 and diff >= 0.1 * b["prev_minor"] and diff >= 50000:
            out.append({"tone": "info", "text": f"{b['name']} is your biggest rise: {fmt_money(diff)} more than last month."})
    top = db.execute(
        f"SELECT merchant, SUM({EXP}) AS amt, COUNT(*) AS n FROM ({LINES}) WHERE month=? AND type='expense' AND kind!='savings' "
        f"AND merchant!='' GROUP BY merchant_key ORDER BY amt DESC LIMIT 1", (user_id, month)).fetchone()
    if top and top["amt"] and top["amt"] > 0:
        out.append({"tone": "info", "text": f"Most spent on one merchant: {top['merchant']}, {fmt_money(top['amt'])} across {top['n']} payment{'s' if top['n'] != 1 else ''}."})
    if inc > 0 and exp >= 0:
        rate = round(100 * (inc - exp) / inc)
        if rate >= 20:
            out.append({"tone": "good", "text": f"You kept {rate}% of your income in {mname}."})
        elif rate < 0:
            out.append({"tone": "warn", "text": f"Spending was {fmt_money(exp - inc)} higher than income in {mname}."})
    ob = d["budgets"]["overall"]
    today = date.today()
    if ob and month == today.strftime("%Y-%m") and today.day >= 3 and exp > 0:
        days = calendar.monthrange(today.year, today.month)[1]
        projected = round(exp / today.day * days)
        if projected > ob["limit_minor"]:
            out.append({"tone": "warn", "text": f"At this pace you'll spend about {fmt_money(projected)} this month, above your {fmt_money(ob['limit_minor'])} limit."})
    over = [b for b in d["budgets"]["items"] if b["pct"] >= 100]
    near = [b for b in d["budgets"]["items"] if 80 <= b["pct"] < 100]
    if over:
        out.append({"tone": "warn", "text": "Over budget: " + ", ".join(b["category_name"] for b in over[:3]) + "."})
    if near:
        out.append({"tone": "info", "text": "Close to budget: " + ", ".join(f"{b['category_name']} ({b['pct']}%)" for b in near[:3]) + "."})
    rec = d["recurring"]
    if rec["count"] and exp > 0:
        out.append({"tone": "info", "text": f"Recurring bills and subscriptions come to about {fmt_money(rec['monthly_total_minor'])} a month."})
    if d["duplicates"]:
        out.append({"tone": "warn", "text": f"{d['duplicates']} possible duplicate transaction{'s' if d['duplicates'] != 1 else ''} are left out of these totals until you check them."})
    return out[:6]
