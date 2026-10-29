"""Password recovery and change regression tests, isolated from real financial data."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
tmp = tempfile.TemporaryDirectory()
os.environ["SPENDFLOW_DATA"] = tmp.name

from fastapi.testclient import TestClient
from backend.main import app
from backend.db import connect
from backend.auth import issue_password_reset

headers = {"x-requested-with": "spendflow"}
client = TestClient(app, headers=headers)
email = "recovery@example.com"
old = "OriginalPassword123!"
new = "UpdatedPassword456!"
changed = "AnotherPassword789!"

assert client.post("/api/auth/register",json={"email":email,"password":old}).status_code == 200
db = connect()
try:
    user_id = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()[0]
    token = issue_password_reset(db, email)
    assert token and len(token) > 32
    assert db.execute("SELECT COUNT(*) FROM password_reset_tokens").fetchone()[0] == 1
finally:
    db.close()

# Wrong token does not change the password.
assert client.post("/api/auth/reset-password",json={"token":"invalid","new_password":new}).status_code == 400
# Successful reset revokes old sessions and token.
assert client.post("/api/auth/reset-password",json={"token":token,"new_password":new}).status_code == 200
assert client.post("/api/auth/reset-password",json={"token":token,"new_password":changed}).status_code == 400
assert client.get("/api/auth/me").status_code == 401
assert client.post("/api/auth/login",json={"email":email,"password":old}).status_code == 401
assert client.post("/api/auth/login",json={"email":email,"password":new}).status_code == 200
assert client.post("/api/auth/change-password",json={"current_password":"wrong","new_password":changed}).status_code == 401
assert client.post("/api/auth/change-password",json={"current_password":new,"new_password":"short"}).status_code == 400
assert client.post("/api/auth/change-password",json={"current_password":new,"new_password":changed}).status_code == 200
assert client.get("/api/auth/me").status_code == 401
assert client.post("/api/auth/login",json={"email":email,"password":changed}).status_code == 200

# Expired codes cannot be redeemed.
db=connect()
try:
    expired=issue_password_reset(db,email)
    db.execute("UPDATE password_reset_tokens SET expires_at='2000-01-01T00:00:00+00:00'")
    db.commit()
finally:
    db.close()
assert client.post("/api/auth/reset-password",json={"token":expired,"new_password":new}).status_code == 400
assert client.get("/api/auth/me").status_code == 200
print("Password recovery checks passed.")
