"""SpendFlow API regression checks for recoverable removal and confirmed flow groups."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
_tmp=tempfile.TemporaryDirectory()
os.environ["SPENDFLOW_DATA"]=_tmp.name

from fastapi.testclient import TestClient
from backend.main import app

client=TestClient(app,headers={"x-requested-with":"spendflow"})
res=client.post("/api/auth/register",json={"email":"spendflow-regression@example.com","password":"password123"})
assert res.status_code==200,res.text
account=client.post("/api/accounts",json={"name":"Main bank","type":"bank"}).json()["id"]
food=next(c["id"] for c in client.get("/api/categories").json() if c["name"]=="Food")

def add(date,amount,direction,desc):
    r=client.post("/api/transactions",json={"account_id":account,"date":date,"amount_minor":amount,"direction":direction,"description":desc})
    assert r.status_code==200,r.text
    return r.json()["txn"]["id"]

a=add("2026-10-18",15000,"debit","transfer to friend")
b=add("2026-10-19",9000,"credit","returned amount first part")
c=add("2026-10-22",6000,"credit","returned amount final part")

assert client.get("/api/review/next").json()["item"]["txn"]["id"]==c
assert client.get("/api/review/next?order=asc").json()["item"]["txn"]["id"]==a
assert client.patch(f"/api/transactions/{a}",json={"category_id":food,"remember":True}).status_code==200
rule=client.get("/api/classification-rules").json()
assert len(rule)==1,rule
assert client.patch(f"/api/classification-rules/{rule[0]['id']}",json={"category_id":food,"type":"expense"}).status_code==200

flow=client.post("/api/flows",json={"kind":"loan","transaction_ids":[a,b,c]})
assert flow.status_code==200,flow.text
gid=flow.json()["id"]
items=client.get("/api/flows").json()
assert len(items)==1 and len(items[0]["transactions"])==3,items
totals=client.get("/api/dashboard?month=2026-10").json()
assert totals["expense_minor"]==totals["income_minor"]==0,totals
assert client.delete(f"/api/flows/{gid}").status_code==200
after=client.get("/api/dashboard?month=2026-10").json()
assert after["expense_minor"]==15000 and after["income_minor"]==15000,after

assert client.post("/api/exclusions",json={"transaction_id":a}).status_code==200
assert len(client.get("/api/exclusions").json())==1
result=client.get("/api/transactions?include_removed=1").json()
assert any(x["id"]==a and x["removed_at"] for x in result["items"])
assert client.post(f"/api/transactions/{a}/restore").status_code==200
assert client.get(f"/api/transactions/{a}").status_code==200

assert client.delete(f"/api/classification-rules/{rule[0]['id']}").status_code==200
exid=client.get("/api/exclusions").json()[0]["id"]
assert client.delete(f"/api/exclusions/{exid}").status_code==200
print("SpendFlow regression checks passed")
