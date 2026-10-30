"""Credit-card statement reader. Uses billing-table boundaries, never illustrative pages."""
import re
from collections import Counter
from .parse_common import group_lines, parse_date, to_minor

DATE = re.compile(r"^\\s*(\\d{1,2})(?:st|nd|rd|th)?\\s+([A-Za-z]{3,9}),?\\s+(20\\d{2})\\b", re.I)
AMOUNT = re.compile(r"(-?)\\s*₹\\s*([\\d,]+\\.\\d{2})")
LAST4 = re.compile(r"(?:[xX*]{4}\\s*){3}(\\d{4})")
def _text(page, i):
    return [line.text.strip() for line in group_lines(page, i)]

def detect_card(pages):
    if not pages: return None
    top = "\\n".join(_text(pages[0],0)[:55])
    if "Utkarsh Small Finance Bank" in top and ("super.money" in top.lower() or "total limit:" in top.lower()):
        m=LAST4.search(top)
        lim=re.search(r"Total Limit:\\s*₹\\s*([\\d,]+\\.\\d{2})",top,re.I)
        due=re.search(r"Payment Due Date.*?Total Amount Due",top,re.I)
        return {"name":"SuperMoney SuperCard", "last4":m.group(1) if m else None,
                "limit_minor":to_minor(lim.group(1)) if lim else None,
                "issuer":"Utkarsh Small Finance Bank"}
    return None

def parse_card(pages):
    info=detect_card(pages)
    if not info: return [],["Unsupported credit-card format"],{}
    rows=[]; warnings=[]; in_table=False
    for pi,page in enumerate(pages):
        lines=_text(page,pi)
        if "All Transactions" in "\\n".join(lines[:10]):
            in_table=True
        elif pi>0 and not in_table:
            continue
        if in_table and any("Customer Care Service" in x or "RBI Ombudsman" in x for x in lines[:25]):
            break
        for line in lines:
            if "All Transactions" in line or ("Date" in line and "Amount (INR)" in line):
                continue
            m=DATE.match(line)
            if not m:
                # Fuel surcharge is a separate debit on a line immediately following its purchase.
                if rows and re.search(r"Fuel Surcharge",line,re.I):
                    a=AMOUNT.search(line)
                    if a:
                        rows.append({"date":rows[-1]["date"],"description":"Fuel Surcharge",
                                     "amount_minor":to_minor(a.group(2)),"direction":"debit",
                                     "flags":["Fuel surcharge shown separately"]})
                continue
            iso=parse_date(" ".join(m.groups()))
            if not iso: continue
            tail=line[m.end():].strip()
            a=list(AMOUNT.finditer(tail))
            if not a: continue
            amt=a[-1]
            description=tail[:amt.start()].strip()
            description=re.sub(r"^(?:UPI|Online)\\s+","",description,flags=re.I).strip()
            if not description: continue
            is_payment=bool(re.fullmatch("Payment",description,re.I))
            refund=amt.group(1)=="-"
            rows.append({"date":iso,"description":description,"amount_minor":to_minor(amt.group(2)),
                         "direction":"credit" if refund or is_payment else "debit",
                         "flags":["Credit card repayment"] if is_payment else (["Credit card refund"] if refund else [])})
    if not rows: warnings.append("No credit-card transactions found; check the statement.")
    # Do not silently reconcile to the cover-page summary: expose any discrepancy.
    first="\\n".join(_text(pages[0],0))
    def summary(label):
        x=re.search(r"^"+re.escape(label)+r"\\s+₹\\s*([\\d,]+\\.\\d{2})",first,re.M|re.I)
        return to_minor(x.group(1)) if x else None
    purchases=sum(r["amount_minor"] for r in rows if r["direction"]=="debit")
    repayments=sum(r["amount_minor"] for r in rows if "Credit card repayment" in r["flags"])
    refunds=sum(r["amount_minor"] for r in rows if "Credit card refund" in r["flags"])
    expected={"purchases":summary("Transactions and EMIs"),"repayments":summary("Repayments"),"refunds":summary("Transaction Reversals and Refunds")}
    for label,actual in (("purchases",purchases),("repayments",repayments),("refunds",refunds)):
        if expected[label] is not None and expected[label]!=actual:
            warnings.append(f"Card {label} mismatch: extracted ₹{actual/100:.2f}, statement ₹{expected[label]/100:.2f}. Review before import.")
    return rows,warnings,info
