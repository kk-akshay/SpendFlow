"""Payee alias safety: stable IDs, owner scope, and future-only merchant correction."""
from __future__ import annotations
import os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
with tempfile.TemporaryDirectory() as td:
    os.environ.pop("DATABASE_URL",None)
    os.environ["SPENDFLOW_DATA"]=td
    from backend.db import init_db, connect
    from backend import payee_names
    from backend.merchants import merchant_key
    init_db()
    db=connect()
    db.execute("INSERT INTO users(email,pw_hash,pw_salt) VALUES('a@test.com',X'11',X'22')")
    db.execute("INSERT INTO users(email,pw_hash,pw_salt) VALUES('b@test.com',X'11',X'22')")
    a=db.execute("SELECT id FROM users WHERE email='a@test.com'").fetchone()[0]
    b=db.execute("SELECT id FROM users WHERE email='b@test.com'").fetchone()[0]
    narration="UPI/665222714748/Dr/MIDH UN P/HDFC/midhunpmidhu009"
    info=payee_names.identity_details(narration)
    assert info and info["kind"]=="bank_reference",info
    assert payee_names.identity_details("UPI/12345/Dr/Person") is None
    payee_names.learn(db,a,info["identity"],"Midhun P")
    original={"merchant":"Midh Un P","description":narration}
    name,key=payee_names.renamed_fields(original,payee_names.all_rules(db,a))
    assert name=="Midhun P" and key==merchant_key("Midhun P")
    assert payee_names.renamed_fields(original,payee_names.all_rules(db,b))[0]=="Midh Un P"
    db.close()
print("Payee naming regression tests passed")
