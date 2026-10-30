"""Credit card limit and conservative repayment integration checks."""
import os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
with tempfile.TemporaryDirectory() as p:
    os.environ.pop("DATABASE_URL",None)
    os.environ["SPENDFLOW_DATA"]=p
    from fastapi.testclient import TestClient
    from backend.main import app
    with TestClient(app,headers={"x-requested-with":"spendflow"}) as c:
        r=c.post("/api/auth/register",json={"email":"cards@example.com","password":"password123"})
        assert r.status_code==200,r.text
        b=c.post("/api/accounts",json={"name":"KGB","type":"bank"}).json()
        cc=c.post("/api/accounts",json={"name":"SuperMoney","type":"card","card_monthly_limit_minor":2000000,"card_credit_limit_minor":5000000,"card_opening_outstanding_minor":30000})
        assert cc.status_code==200,cc.text
        card=cc.json()
        assert card["card_monthly_limit_minor"]==2000000
        a=c.post("/api/transactions",json={"account_id":card["id"],"date":"2026-10-13","amount_minor":150000,"direction":"debit","description":"Amazon purchase"})
        assert a.status_code==200,a.text
        overview=c.get("/api/credit-cards?month=2026-10").json()["cards"][0]
        assert overview["spent_minor"]==150000,overview
        assert overview["remaining_minor"]==1850000
        assert overview["outstanding_minor"]==180000,overview
        assert overview["available_credit_minor"]==4820000,overview
        assert overview["utilization_percent"]==3.6,overview
        bank=c.post("/api/transactions",json={"account_id":b["id"],"date":"2026-10-16","amount_minor":150000,"direction":"debit","description":"SuperMoney credit card payment"}).json()
        credit=c.post("/api/transactions",json={"account_id":card["id"],"date":"2026-10-16","amount_minor":150000,"direction":"credit","description":"Card bill received"}).json()
        all_txns=c.get("/api/transactions?sort=date_desc&limit=100").json()["items"]
        bank=next(t for t in all_txns if t["description"]=="SuperMoney credit card payment")
        credit=next(t for t in all_txns if t["description"]=="Card bill received")
        data=c.get("/api/credit-cards?month=2026-10").json()["cards"][0]
        assert len(data["repayment_suggestions"])==1,data
        suggestion=data["repayment_suggestions"][0]
        assert suggestion["bank_txn_id"]==bank["id"],suggestion
        assert suggestion["card_txn_id"]==credit["id"],suggestion
        verified=c.post(f"/api/credit-cards/{card['id']}/repayments/{bank['id']}/confirm")
        assert verified.status_code==200,verified.text
        for ident in [bank["id"],credit["id"]]:
            x=c.get("/api/transactions/"+str(ident)).json()["txn"]
            assert x["type"]=="transfer" and x["transfer_pair_id"] is not None,x
        new=c.get("/api/credit-cards?month=2026-10").json()["cards"][0]
        assert not new["repayment_suggestions"]
        assert new["outstanding_minor"]==180000,new
        assert new["available_credit_minor"]==4820000,new
        assert new["utilization_percent"]==3.6,new
        edit=c.patch("/api/accounts/"+str(card["id"]),json={"name":"SuperMoney Card","type":"card","last4":"1234"})
        assert edit.status_code==200 and edit.json()["card_monthly_limit_minor"]==2000000,edit.text
        assert edit.json()["card_credit_limit_minor"]==5000000 and edit.json()["card_opening_outstanding_minor"]==30000
print("Credit card checks passed")
