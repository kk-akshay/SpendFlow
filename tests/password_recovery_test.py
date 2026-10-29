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
from unittest.mock import patch

headers = {"x-requested-with": "spendflow"}
client = TestClient(app, headers=headers)
email = "recovery@example.com"
old = "OriginalPassword123!"
new = "UpdatedPassword456!"
changed = "AnotherPassword789!"

assert client.get("/api/auth/session").json() == {"authenticated":False,"user":None}
assert client.post("/api/auth/register",json={"email":email,"password":old}).status_code == 200
assert client.get("/api/auth/session").json()["user"]["email"] == email
assert client.post("/api/auth/register",json={"email":email,"password":old}).status_code == 409
db = connect()
try:
    user_id = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()[0]
    token = issue_password_reset(db, email)
    assert token and len(token) > 32
    assert db.execute("SELECT COUNT(*) FROM password_reset_tokens").fetchone()[0] == 1
finally:
    db.close()

# Browser email endpoint is safely disabled when SMTP is not configured.
assert client.post("/api/auth/forgot-password",json={"email":email}).status_code == 503

# With a configured mail transport, a code is delivered only for a known account.
sent=[]
def capture(recipient, code):
    sent.append((recipient,code))
with patch("backend.main.mail_recovery_available", return_value=True), patch("backend.main.send_password_reset_email", side_effect=capture):
    assert client.post("/api/auth/forgot-password",json={"email":"missing@example.com"}).status_code == 200
    assert sent == []
    assert client.post("/api/auth/forgot-password",json={"email":email}).status_code == 200
    assert len(sent)==1 and sent[0][0]==email
    token=sent[0][1]

# Wrong token does not change the password.
assert client.post("/api/auth/reset-password",json={"token":"invalid","new_password":new}).status_code == 400
# Successful reset revokes old sessions and token.
assert client.post("/api/auth/reset-password",json={"token":token,"new_password":new}).status_code == 200
assert client.post("/api/auth/reset-password",json={"token":token,"new_password":changed}).status_code == 400
assert client.get("/api/auth/me").status_code == 401
assert client.get("/api/auth/session").json()["authenticated"] is False
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
