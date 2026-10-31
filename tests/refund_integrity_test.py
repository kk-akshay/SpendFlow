"""Regression: legacy linking must never remove refund type or double-count a purchase."""
import os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
_tmp=tempfile.TemporaryDirectory()
os.environ["SPENDFLOW_DATA"]=_tmp.name
os.environ.pop("DATABASE_URL",None)
from fastapi.testclient import TestClient
from backend.main import app
with TestClient(app,headers={"x-requested-with":"spendflow"}) as c:
    def ok(r):
        assert r.status_code==200,(r.status_code,r.text)
        return r.json()
    ok(c.post("/api/auth/register",json={"email":"refund-integrity@example.com","password":"password123"}))
    bank=ok(c.post("/api/accounts",json={"name":"Bank","type":"bank"}))["id"]
    card=ok(c.post("/api/accounts",json={"name":"Card","type":"card","card_monthly_limit_minor":300000}))["id"]
    cats={x["name"]:x["id"] for x in ok(c.get("/api/categories"))}
    def add(acc,day,minor,direction,desc):
        return ok(c.post("/api/transactions",json={"account_id":acc,"date":day,
            "amount_minor":minor,"direction":direction,"description":desc}))["txn"]["id"]
    purchase=add(card,"2026-10-20",40000,"debit","Train booking")
    refund=add(card,"2026-11-05",20000,"credit","Train cancellation refund")
    ok(c.patch(f"/api/transactions/{purchase}",json={"category_id":cats["Travel"]}))
    ok(c.patch(f"/api/transactions/{refund}",json={"category_id":cats["Travel"],"type":"refund"}))
    ok(c.post(f"/api/transactions/{refund}/refund-link",json={"original_id":purchase}))
    def spend():
        return ok(c.get("/api/dashboard?month=2026-10"))["expense_minor"]
    assert spend()==20000
    card_view=ok(c.get("/api/credit-cards?month=2026-10"))["cards"][0]
    assert card_view["spent_minor"]==20000,card_view
    november=ok(c.get("/api/credit-cards?month=2026-11"))["cards"][0]
    assert november["spent_minor"]==0,november
    assert november["outstanding_minor"]==20000,november
    # Linked refunds and their original expenses must not join older transfer systems.
    for a,b in [(refund,purchase),(purchase,refund)]:
        assert c.post("/api/flows",json={"kind":"loan","transaction_ids":[a,b]}).status_code==400
        assert c.post("/api/groups",json={"name":"Group","kind":"transfer","ids":[a,b]}).status_code==400
    assert spend()==20000
    others=add(bank,"2026-11-04",20000,"debit","Card bill repayment")
    assert c.post("/api/flows",json={"kind":"loan","transaction_ids":[others,purchase]}).status_code==400
    assert spend()==20000
    # Old bulk edit must not override the accounting type of a flow member.
    assert c.patch(f"/api/transactions/{refund}",json={"direction":"debit"}).status_code==400
    assert spend()==20000
    # Current original purchase remains available among edit-link suggestions.
    matches=ok(c.get(f"/api/transactions/{refund}/refund-candidates"))
    assert any(x["id"]==purchase and x["remaining_minor"]==20000 for x in matches),matches
    assert ok(c.get(f"/api/transactions/{refund}"))["txn"]["is_refund"]
    assert ok(c.get(f"/api/dashboard?month=2026-11"))["income_minor"]==0
print("Refund integrity and card spending regressions passed.")
