"""People/UPI loan ledger regression suite using an isolated SQLite database."""
import os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
tmp=tempfile.TemporaryDirectory()
os.environ["SPENDFLOW_DATA"]=tmp.name
from fastapi.testclient import TestClient
from backend.main import app
client=TestClient(app,headers={"x-requested-with":"spendflow"})
assert client.post("/api/auth/register",json={"email":"people@example.com","password":"StrongPassword123!"}).status_code==200
bank=client.post("/api/accounts",json={"name":"Bank","type":"bank"}).json()["id"]
def add(d,amount,direction,desc):
    resp=client.post("/api/transactions",json={"account_id":bank,"date":d,"amount_minor":amount,"direction":direction,"description":desc})
    assert resp.status_code==200,resp.text
    return resp.json()["txn"]["id"]
a=add("2026-10-10",15000,"debit","UPI/ARUN/arun@okaxis")
b=add("2026-10-12",9000,"credit","UPI/ARUN/arun@oksbi")
c=add("2026-10-20",6000,"credit","UPI/ARUN/arun@okaxis")
d=add("2026-10-22",5000,"debit","UPI/other/other@okaxis")
before=client.get("/api/dashboard?month=2026-10").json()
assert before["expense_minor"]==20000 and before["income_minor"]==15000,before
suggest=client.get(f"/api/people/transaction/{a}/suggestions")
assert suggest.status_code==200,suggest.text
assert "arun@okaxis" in suggest.json()["upi_ids"],suggest.json()
p=client.post("/api/people",json={"name":"Arun (from UPI)"}).json()["id"]
assert client.patch(f"/api/people/{p}",json={"name":"Arun Kumar"}).status_code==200
assert client.post(f"/api/people/{p}/upi",json={"upi_id":"Arun@OKAXIS"}).status_code==200
assert client.post(f"/api/people/{p}/upi",json={"upi_id":"arun@oksbi"}).status_code==200
assert client.post(f"/api/people/{p}/upi",json={"upi_id":"arun@okaxis"}).status_code==400
assert client.get(f"/api/people/transaction/{a}/suggestions").json()["exact_people"][0]["id"]==p
candidate=client.get(f"/api/people/{p}/candidates").json()
assert {a,b,c}.issubset({x["id"] for x in candidate}),candidate
assert d not in {x["id"] for x in candidate}
assert client.post(f"/api/people/{p}/transactions",json={"txn_id":a,"role":"repaid"}).status_code==400
for tid,role in [(a,"lent"),(b,"repaid"),(c,"repaid")]:
    resp=client.post(f"/api/people/{p}/transactions",json={"txn_id":tid,"role":role})
    assert resp.status_code==200,resp.text
assert client.post(f"/api/people/{p}/transactions",json={"txn_id":a,"role":"lent"}).status_code==400
ledger=client.get("/api/people").json()[0]
assert ledger["name"]=="Arun Kumar" and len(ledger["upi_ids"])==2
assert ledger["lent_minor"]==15000 and ledger["repaid_minor"]==15000
assert ledger["owed_to_me_minor"]==0
after=client.get("/api/dashboard?month=2026-10").json()
assert after["expense_minor"]==5000 and after["income_minor"]==0,after
assert client.patch(f"/api/transactions/{a}",json={"amount_minor":1000}).status_code==400
assert client.get(f"/api/transactions/{a}").json()["txn"]["amount_minor"]==15000
assert client.delete(f"/api/people/{p}/transactions/{b}").status_code==200
assert client.get("/api/people").json()[0]["owed_to_me_minor"]==9000
alias=client.get("/api/people").json()[0]["upi_ids"][0]["id"]
assert client.delete(f"/api/people/{p}/upi/{alias}").status_code==200
assert client.delete(f"/api/people/{p}").status_code==200
restored=client.get("/api/dashboard?month=2026-10").json()
assert restored["expense_minor"]==20000 and restored["income_minor"]==15000,restored
assert client.get(f"/api/transactions/{a}").json()["txn"]["amount_minor"]==15000
print("Person-based loan tracking checks passed")
