"""Focused ledger regression tests. Uses an isolated temporary SQLite database."""
import os
import tempfile
from pathlib import Path

_tmp = tempfile.TemporaryDirectory()
os.environ["TALLY_DATA"] = _tmp.name

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app, headers={"x-requested-with": "tally"})
assert client.post("/api/auth/register", json={"email":"ledger-test@example.com","password":"password123"}).status_code == 200
account = client.post("/api/accounts", json={"name":"Test bank","type":"bank"}).json()["id"]
food = next(c["id"] for c in client.get("/api/categories").json() if c["name"] == "Food")

def create(day,amount,direction,description):
    res=client.post("/api/transactions",json={"account_id":account,"date":day,"amount_minor":amount,"direction":direction,"description":description})
    assert res.status_code == 200, res.text
    return res.json()["txn"]["id"]

a=create("2026-10-18",15000,"debit","loan to friend")
b=create("2026-10-19",9000,"credit","friend repayment")
c=create("2026-10-22",6000,"credit","friend repayment balance")
assert client.get("/api/review/next").json()["item"]["txn"]["id"] == c
assert client.get("/api/review/next?order=asc").json()["item"]["txn"]["id"] == a
assert client.post(f"/api/review/{c}/skip").status_code == 200
assert client.get("/api/review/next").json()["item"]["txn"]["id"] == b
assert client.get("/api/review/next?scope=skipped").json()["item"]["txn"]["id"] == c

before = client.get("/api/dashboard?month=2026-10").json()
assert before["expense_minor"] == 15000 and before["income_minor"] == 15000
match=client.get(f"/api/transactions/{a}/matches")
assert match.status_code==200 and isinstance(match.json(),list)
g=client.post("/api/groups",json={"name":"Small loan","kind":"loan","ids":[a,b]})
assert g.status_code==200,g.text
gid=g.json()["id"]
after=client.get("/api/dashboard?month=2026-10").json()
assert after["expense_minor"] == 0 and after["income_minor"] == 6000
assert client.patch(f"/api/transactions/{a}",json={"type":"expense"}).status_code == 400
assert client.post(f"/api/groups/{gid}/members",json={"ids":[c]}).status_code == 200
assert client.get("/api/groups").json()[0]["unsettled_minor"] == 0
assert client.get("/api/dashboard?month=2026-10").json()["income_minor"] == 0
assert client.delete(f"/api/groups/{gid}").status_code==200
restored=client.get("/api/dashboard?month=2026-10").json()
assert restored["expense_minor"]==15000 and restored["income_minor"]==15000

assert client.patch(f"/api/transactions/{a}",json={"category_id":food,"remember":True}).status_code==200
rules=client.get("/api/rules").json()
assert len(rules["classifications"])==1
assert client.post(f"/api/transactions/{b}/exclude",json={"confirmed":False}).status_code==400
assert client.post(f"/api/transactions/{b}/exclude",json={"confirmed":True}).status_code==200
assert len(client.get("/api/rules").json()["exclusions"])==1
assert client.get(f"/api/transactions/{b}").status_code==404
rule=client.get("/api/rules").json()["exclusions"][0]
assert client.delete(f"/api/rules/exclusion/{rule['id']}").status_code==200
assert client.get("/api/transactions?sort=date_desc").json()["items"][0]["date"]=="2026-10-22"
assert client.get("/api/transactions?from=2026-10-18&to=2026-10-18").json()["total"]==1
print("Focused ledger regression checks passed.")
