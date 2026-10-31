"""Unified refund accounting and ownership regressions (isolated SQLite API)."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
_tmp = tempfile.TemporaryDirectory()
os.environ["SPENDFLOW_DATA"] = _tmp.name
os.environ.pop("DATABASE_URL",None)
from fastapi.testclient import TestClient
from backend.main import app

c=TestClient(app,headers={"x-requested-with":"spendflow"})
def ok(result):
    assert result.status_code==200, (result.status_code,result.text)
    return result.json()
ok(c.post("/api/auth/register",json={"email":"refund-tests@example.com","password":"password123"}))
account=ok(c.post("/api/accounts",json={"name":"Bank","type":"bank"}))["id"]
cats={x["name"]:x["id"] for x in ok(c.get("/api/categories"))}
food, travel=cats["Food"],cats["Travel"]
tag=ok(c.post("/api/tags",json={"name":"Trip","kind":"trip"}))["id"]
def add(day,amount,direction,name):
    return ok(c.post("/api/transactions",json={
        "account_id":account,"date":day,"amount_minor":amount,
        "direction":direction,"description":name
    }))["txn"]["id"]
def classify(tid,category,typ=None):
    body={"category_id":category}
    if typ:body["type"]=typ
    return ok(c.patch(f"/api/transactions/{tid}",json=body))
def link(refund,purchase):
    return ok(c.post(f"/api/transactions/{refund}/refund-link",json={"original_id":purchase}))
def dashboard(month):
    return ok(c.get("/api/dashboard?month="+month))
def total(month):
    return dashboard(month)["expense_minor"]

# 400 purchase, 200 partial refund, original October reporting date.
purchase=add("2026-10-20",40000,"debit","IRCTC Train Booking")
classify(purchase,travel)
ok(c.put(f"/api/transactions/{purchase}/tags",json={"tag_ids":[tag]}))
r1=add("2026-11-05",20000,"credit","IRCTC cancellation")
classify(r1,travel,"refund")
assert total("2026-10")==40000
assert total("2026-11")==-20000, dashboard("2026-11")
suggestions=ok(c.get(f"/api/transactions/{r1}/refund-candidates"))
assert any(x["id"]==purchase for x in suggestions),suggestions
link(r1,purchase)
assert total("2026-10")==20000, dashboard("2026-10")
assert total("2026-11")==0, dashboard("2026-11")
assert dashboard("2026-11")["income_minor"]==0
details=ok(c.get(f"/api/transactions/{purchase}"))["txn"]
assert details["refunded_minor"]==20000 and details["refund_status"]=="partially"
assert ok(c.get(f"/api/transactions/{r1}"))["txn"]["original_expense"]["id"]==purchase
assert ok(c.get("/api/tags"))[0]["expense_minor"]==20000
assert ok(c.get("/api/tags/"+str(tag)+"/transactions"))["transactions"][0]["id"]==purchase
assert total("2026-10")==20000 # repeated dashboard calls cannot double-count
# Partial refund totals should also feed budgets.
ok(c.put("/api/budgets",json={"category_id":travel,"limit_minor":100000}))
assert next(b for b in ok(c.get("/api/budgets?month=2026-10"))["items"] if b["category_id"]==travel)["spent_minor"]==20000
# Never allow over-refunding.
too_much=add("2026-11-06",30000,"credit","another cancellation")
classify(too_much,travel,"refund")
assert c.post(f"/api/transactions/{too_much}/refund-link",json={"original_id":purchase}).status_code==400
# Unlinking restores purchase cost and leaves the incoming refund as negative spending.
ok(c.delete(f"/api/transactions/{r1}/refund-link"))
assert total("2026-10")==40000 and total("2026-11")==-50000
link(r1,purchase)
# Distinct purchase, two partial refunds.
second=add("2026-10-18",100000,"debit","Other tickets")
classify(second,food)
s1=add("2026-10-19",30000,"credit","Partial refund one")
s2=add("2026-11-14",20000,"credit","Partial refund two")
for t in (s1,s2):classify(t,food,"refund")
link(s1,second);link(s2,second)
assert ok(c.get(f"/api/transactions/{second}"))["txn"]["net_expense_minor"]==50000
assert total("2026-10")==70000
# Fully refunded expense.
full=add("2026-10-10",40000,"debit","Cancelled order")
fullrefund=add("2026-10-11",40000,"credit","Cancelled order refund")
classify(full,food);classify(fullrefund,food,"refund")
link(fullrefund,full)
assert ok(c.get(f"/api/transactions/{full}"))["txn"]["refund_status"]=="fully"
assert total("2026-10")==70000
# An unlinked refund affects its own month and assigned expense category.
unlinked=add("2026-11-20",5000,"credit","Store refund")
classify(unlinked,food,"refund")
assert total("2026-11")==-35000 # 30000 unlinked + 5000 unlinked
assert dashboard("2026-11")["income_minor"]==0
# Cross-user matching and link requests are never permitted.
other=TestClient(app,headers={"x-requested-with":"spendflow"})
ok(other.post("/api/auth/register",json={"email":"other-refund@example.com","password":"password123"}))
other_account=ok(other.post("/api/accounts",json={"name":"Other bank","type":"bank"}))["id"]
foreign=ok(other.post("/api/transactions",json={"account_id":other_account,"date":"2026-11-17",
                    "amount_minor":5000,"direction":"credit","description":"Refund"}))["txn"]["id"]
other_food=next(x["id"] for x in ok(other.get("/api/categories")) if x["name"]=="Food")
ok(other.patch(f"/api/transactions/{foreign}",json={"category_id":other_food,"type":"refund"}))
assert other.post(f"/api/transactions/{foreign}/refund-link",json={"original_id":purchase}).status_code==400
assert c.post(f"/api/transactions/{r1}/refund-link",json={"original_id":foreign}).status_code==400
# Cash-flow is still the original debit and credit dated bank transactions.
history=ok(c.get("/api/transactions?from=2026-11-05&to=2026-11-05"))
assert len(history["items"])==1 and history["items"][0]["amount_minor"]==20000
assert history["items"][0]["direction"]=="credit"
print("Unified refund API and ledger regression checks passed")
