"""Exercise SQLite to PostgreSQL migration with synthetic linked data."""
import os
import tempfile
import sqlite3
from pathlib import Path

assert os.environ.get("SPENDFLOW_TEST_DATABASE") == "1"
from backend.db import SCHEMA
from backend.migrate_sqlite import run
from backend.postgres import pool

with tempfile.TemporaryDirectory() as td:
    src = Path(td) / "tally.db"
    db = sqlite3.connect(src)
    db.executescript(SCHEMA)
    db.execute("INSERT INTO users(id,email,pw_hash,pw_salt) VALUES(?,?,?,?)",
               (12,"demo@example.com",b"fake-hash",b"fake-salt"))
    db.execute("INSERT INTO accounts(id,user_id,name) VALUES(?,?,?)",(18,12,"Bank"))
    db.execute("INSERT INTO categories(id,user_id,name,color) VALUES(?,?,?,?)",
               (24,12,"Food","#000000"))
    db.execute("INSERT INTO transactions(id,user_id,account_id,date,amount_minor,direction,type,merchant,status,category_id) "
               "VALUES(?,?,?,?,?,?,?,?,?,?)",
               (32,12,18,"2026-10-10",1299,"debit","expense","Cafe","categorized",24))
    db.execute("INSERT INTO merchant_rules(user_id,merchant_key,category_id) VALUES(?,?,?)",
               (12,"cafe",24))
    db.commit()
    db.close()
    run(src,False)
    run(src,True)
    with pool().connection() as dest:
        assert dest.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 1
        assert dest.execute("SELECT amount_minor,category_id FROM transactions WHERE id=32").fetchone() == {
            "amount_minor":1299,"category_id":24
        }
        assert dest.execute("SELECT category_id FROM merchant_rules WHERE user_id=12").fetchone()["category_id"] == 24
        assert dest.execute("SELECT nextval(pg_get_serial_sequence('transactions','id')) AS n").fetchone()["n"] > 32
print("PostgreSQL data migration test passed")
