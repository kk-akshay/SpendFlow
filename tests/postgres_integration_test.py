"""API smoke checks against a real disposable PostgreSQL instance.

DATABASE_URL must point to a disposable database; never use a real ledger.
"""
import os
assert os.getenv("SPENDFLOW_TEST_DATABASE") == "1", "Refusing to run without SPENDFLOW_TEST_DATABASE=1"
assert os.getenv("DATABASE_URL"), "DATABASE_URL is required"

from fastapi.testclient import TestClient
from backend.main import app

c = TestClient(app, headers={"x-requested-with": "spendflow"})
r = c.get("/api/config")
assert r.status_code == 200, r.text
r = c.post("/api/auth/register", json={"email": "postgres-regression@example.com",
                                       "password": "test-password-12345"})
assert r.status_code == 200, r.text
r = c.post("/api/accounts", json={"name": "Main account", "type": "bank"})
assert r.status_code == 200, r.text
account = r.json()["id"]
r = c.get("/api/categories")
assert r.status_code == 200, r.text
food = next(x["id"] for x in r.json() if x["name"] == "Food")
r = c.post("/api/transactions", json={"account_id": account, "date": "2026-09-15",
                                       "amount_minor": 12500, "direction": "debit",
                                       "description": "Dinner"})
assert r.status_code == 200, r.text
tid = r.json()["txn"]["id"]
r = c.patch(f"/api/transactions/{tid}", json={"category_id": food, "remember": True})
assert r.status_code == 200, r.text
for url in [
    "/api/review/next", "/api/transactions", "/api/dashboard",
    "/api/recurring", "/api/budgets", "/api/accounts",
    "/api/classification-rules", "/api/statements",
]:
    res = c.get(url)
    assert res.status_code == 200, (url, res.status_code, res.text)
r = c.get("/api/transactions?q=Dinner")
assert r.status_code == 200 and r.json()["total"] == 1, r.text
r = c.get("/api/transactions?sort=date_asc")
assert r.status_code == 200, r.text
r = c.delete(f"/api/transactions/{tid}")
assert r.status_code == 200, r.text
r = c.get("/api/transactions?include_removed=1")
assert r.status_code == 200 and r.json()["total"] == 1, r.text
print("PostgreSQL integration test passed")
