"""Generate synthetic statements (with ground truth) to test the parsers.

Usage: python tests/make_samples.py <output_dir>
Writes several PDFs/images plus truth.json describing the expected transactions of each.
"""
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

NARRATIONS = [
    ("UPI/412345678901/SWIGGY/swiggy@axisbank/Payment", "d", (150, 900)),
    ("UPI/412345678902/BIGBASKET/bigbasket@icici/Groceries", "d", (500, 3500)),
    ("NEFT CR-HDFC0000001-ACME CORP LTD-SALARY", "c", (60000, 90000)),
    ("ATM WDL 1234XXXXXX5678 KOCHI", "d", (1000, 10000)),
    ("UPI/412345678903/Rahul K/rahul@oksbi/rent", "d", (8000, 16000)),
    ("POS 4321XXXXXXXX1234 AMAZON PAY INDIA", "d", (300, 5000)),
    ("INT.PD:01-07-2026 TO 30-09-2026", "c", (200, 900)),
    ("UPI/412345678904/NETFLIX/netflix@icici/Subscription", "d", (199, 799)),
    ("IMPS-512345678905-MOM-HDFC-Pocket money", "c", (1000, 5000)),
    ("UPI/412345678906/UBER INDIA/uber@axis/Ride", "d", (80, 600)),
    ("UPI/412345678907/Chaayakada/paytm-123@ptys/Tea", "d", (20, 120)),
    ("ECOM PUR/FLIPKART INTERNET PVT LTD", "d", (500, 9000)),
    ("UPI/412345678908/KSEB LTD/kseb@sbi/Electricity bill", "d", (400, 3000)),
    ("UPI/412345678909/Priya S/priya@okaxis/Refund for dinner", "c", (100, 1500)),
]


def make_txns(n=45, seed=7, start=date(2026, 8, 1), opening=50000.0):
    rnd = random.Random(seed)
    out, bal, d = [], opening, start
    for i in range(n):
        d += timedelta(days=rnd.choice([0, 0, 1, 1, 2]))
        narr, kind, (lo, hi) = rnd.choice(NARRATIONS)
        amt = round(rnd.uniform(lo, hi), 2)
        bal = round(bal + amt if kind == "c" else bal - amt, 2)
        out.append({"date": d.isoformat(), "narr": narr, "dir": "credit" if kind == "c" else "debit",
                    "amount": amt, "balance": bal})
    return out, opening


def money(v):
    return f"{v:,.2f}"


def wrap(text, width=30):
    parts, cur = [], ""
    for tok in text.replace("/", "/ ").split(" "):
        if len(cur) + len(tok) + 1 > width and cur:
            parts.append(cur.rstrip())
            cur = ""
        cur += tok + " "
    if cur.strip():
        parts.append(cur.rstrip())
    return [p.replace("/ ", "/") for p in parts] or [text]


def hdfc_ruled(path, txns, opening):
    """Ruled table, ascending, two-line narrations, value-date column, header repeated per page."""
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    cols = {"date": 30, "narr": 80, "ref": 245, "vdate": 322}
    WD_R, DEP_R, BAL_R = 440, 505, 572

    def header(y):
        c.setFont("Helvetica", 9)
        c.drawString(30, H - 40, "HDFC BANK LTD  -  Statement of account")
        c.drawString(30, H - 54, "Account No : 50100123451234     Opening Balance 50,000.00")
        c.setFont("Helvetica-Bold", 8)
        c.drawString(cols["date"], y, "Date")
        c.drawString(cols["narr"], y, "Narration")
        c.drawString(cols["ref"], y, "Chq./Ref.No.")
        c.drawString(cols["vdate"], y, "Value Dt")
        c.drawRightString(WD_R, y, "Withdrawal Amt.")
        c.drawRightString(DEP_R, y, "Deposit Amt.")
        c.drawRightString(BAL_R, y, "Closing Balance")
        c.line(25, y - 4, W - 20, y - 4)

    y = H - 90
    header(y)
    y -= 20
    c.setFont("Helvetica", 8)
    for t in txns:
        lines = wrap(t["narr"], 32)
        need = 11 * len(lines) + 6
        if y - need < 60:
            c.showPage()
            y = H - 60
            header(y)
            y -= 20
            c.setFont("Helvetica", 8)
        d = date.fromisoformat(t["date"])
        c.drawString(cols["date"], y, d.strftime("%d/%m/%y"))
        c.drawString(cols["vdate"], y, d.strftime("%d/%m/%y"))
        for i, ln in enumerate(lines):
            c.drawString(cols["narr"], y - 11 * i, ln)
        if t["dir"] == "debit":
            c.drawRightString(WD_R, y, money(t["amount"]))
        else:
            c.drawRightString(DEP_R, y, money(t["amount"]))
        c.drawRightString(BAL_R, y, money(t["balance"]))
        y -= need
        c.line(25, y + 7, W - 20, y + 7)
    c.setFont("Helvetica", 7)
    c.drawString(30, 40, "This is a computer generated statement. Registered office: Mumbai. Page 1")
    c.save()


def plain_debit_credit(path, txns, opening):
    """No ruling, Debit/Credit/Balance columns, newest first, dd-Mon-yyyy dates."""
    rev = list(reversed(txns))
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    y = H - 60
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "Federal Bank - Account Statement")
    y -= 30

    def header(y):
        c.setFont("Helvetica-Bold", 9)
        c.drawString(40, y, "Txn Date")
        c.drawString(120, y, "Particulars")
        c.drawRightString(400, y, "Debit")
        c.drawRightString(470, y, "Credit")
        c.drawRightString(555, y, "Balance")

    header(y)
    y -= 18
    c.setFont("Helvetica", 8.5)
    for t in rev:
        if y < 60:
            c.showPage()
            y = H - 60
            header(y)
            y -= 18
            c.setFont("Helvetica", 8.5)
        d = date.fromisoformat(t["date"])
        c.drawString(40, y, d.strftime("%d-%b-%Y"))
        c.drawString(120, y, t["narr"][:48])
        c.drawRightString(400 if t["dir"] == "debit" else 470, y, money(t["amount"]))
        c.drawRightString(555, y, money(t["balance"]))
        y -= 15
    c.save()


def amount_drcr(path, txns, opening):
    """Single Amount column with Dr/Cr suffix and a Balance column; no separate debit/credit columns."""
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    y = H - 60
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "State Bank of India  Statement")
    y -= 28
    c.setFont("Helvetica-Bold", 9)
    c.drawString(40, y, "Date")
    c.drawString(115, y, "Description")
    c.drawRightString(440, y, "Amount")
    c.drawRightString(540, y, "Balance")
    y -= 18
    c.setFont("Helvetica", 8.5)
    for t in txns:
        if y < 60:
            c.showPage()
            y = H - 60
            c.setFont("Helvetica", 8.5)
        d = date.fromisoformat(t["date"])
        c.drawString(40, y, d.strftime("%d/%m/%Y"))
        c.drawString(115, y, t["narr"][:50])
        c.drawRightString(440, y, money(t["amount"]) + (" Dr" if t["dir"] == "debit" else " Cr"))
        c.drawRightString(540, y, money(t["balance"]))
        y -= 15
    c.save()


GPAY = [
    ("Paid to Swiggy", "debit", 349.0, "400112233401", "Paid by HDFC Bank 1234"),
    ("Paid to Chaayakada", "debit", 40.0, "400112233402", "Paid by HDFC Bank 1234"),
    ("Received from Priya S", "credit", 500.0, "400112233403", "Credited to HDFC Bank 1234"),
    ("Paid to BigBasket", "debit", 1250.5, "400112233404", "Paid by HDFC Bank 1234"),
    ("Paid to Uber India", "debit", 212.0, "400112233405", "Paid by Federal Bank 9876"),
    ("Received from Rahul K", "credit", 2500.0, "400112233406", "Credited to Federal Bank 9876"),
    ("Paid to Netflix", "debit", 649.0, "400112233407", "Paid by HDFC Bank 1234"),
    ("Paid to Rahul K", "debit", 15000.0, "400112233408", "Paid by HDFC Bank 1234"),
]


def gpay_pdf(path):
    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    y = H - 60
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, y, "Google Pay")
    y -= 20
    c.setFont("Helvetica", 9)
    c.drawString(40, y, "Transaction statement for 9876543210")
    y -= 14
    c.drawString(40, y, "01 August 2026 - 31 August 2026")
    y -= 30
    c.setFont("Helvetica-Bold", 9)
    c.drawString(40, y, "Date & time")
    c.drawString(160, y, "Transaction details")
    c.drawRightString(550, y, "Amount")
    y -= 22
    truth = []
    d = date(2026, 8, 3)
    for i, (title, direction, amt, ref, by) in enumerate(GPAY):
        d += timedelta(days=1 + i % 3)
        c.setFont("Helvetica", 9)
        c.drawString(40, y, d.strftime("%d%b, %Y"))
        c.drawString(160, y, title)
        amt_txt = f"₹{amt:,.0f}" if amt == int(amt) else f"₹{amt:,.2f}"
        c.drawRightString(550, y, amt_txt)
        y -= 12
        c.setFont("Helvetica", 8)
        c.drawString(40, y, f"{9 + i}:{10 + i * 3:02d} PM")
        c.drawString(160, y, f"UPI Transaction ID: {ref}")
        y -= 11
        c.drawString(160, y, by)
        y -= 24
        truth.append({"date": d.isoformat(), "dir": direction, "amount": amt, "narr": title})
    c.save()
    return truth


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    txns, opening = make_txns()
    truth = {
        "hdfc_ruled.pdf": txns,
        "plain_dr_cr.pdf": list(reversed(txns)),
        "amount_drcr.pdf": txns,
    }
    hdfc_ruled(out / "hdfc_ruled.pdf", txns, opening)
    plain_debit_credit(out / "plain_dr_cr.pdf", txns, opening)
    amount_drcr(out / "amount_drcr.pdf", txns, opening)
    truth["gpay.pdf"] = gpay_pdf(out / "gpay.pdf")

    # Image + scanned PDF variants built from the first page of the ruled statement.
    import pdfplumber
    from PIL import Image, ImageFilter

    with pdfplumber.open(out / "hdfc_ruled.pdf") as pdf:
        img = pdf.pages[0].to_image(resolution=150).original.convert("RGB")
    img.save(out / "hdfc_page1.png")
    img.filter(ImageFilter.GaussianBlur(0.6)).save(out / "hdfc_page1.jpg", quality=70)
    img.save(out / "hdfc_scanned.pdf", "PDF", resolution=150)
    (out / "truth.json").write_text(json.dumps(truth, indent=1))
    print("wrote", sorted(p.name for p in out.iterdir()))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tests/samples")
