"""SpendFlow API + static frontend."""
from __future__ import annotations

import csv
import sqlite3
import hashlib
import io
import json
import re
import shutil
import uuid
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import analytics, importing, ledger, parse_llm, txns, people, storage
from .auth import (EMAIL_RE, clear_throttle, current_user, end_session, hash_password, require_csrf,
                   start_session, throttle, verify_password, redeem_password_reset, update_password, issue_password_reset, mail_recovery_available, send_password_reset_email)
from .config import (CURRENCY, FRONTEND_DIR, LOCALE, MAX_FILES_PER_IMPORT, MAX_UPLOAD_BYTES, UPLOAD_DIR)
from .db import get_db, init_db, seed_categories
from .extract import PasswordRequired, UnreadableDocument, sniff_kind
from .merchants import extract_merchant, merchant_key
from .parse_common import parse_date
from .statement_parser import parse_file

init_db()
app = FastAPI(title="SpendFlow", docs_url=None, redoc_url=None, dependencies=[Depends(require_csrf)])


@app.exception_handler(RequestValidationError)
async def _validation(_: Request, exc: RequestValidationError):
    return JSONResponse({"detail": "Some details were missing or not valid. Please check and try again."}, status_code=400)


@app.exception_handler(LookupError)
async def _lookup(_: Request, exc: LookupError):
    return JSONResponse({"detail": str(exc) or "Not found."}, status_code=404)


@app.exception_handler(ValueError)
async def _value(_: Request, exc: ValueError):
    return JSONResponse({"detail": str(exc)}, status_code=400)


MIME = {"pdf": "application/pdf", "png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}
EXT = {"pdf": ".pdf", "png": ".png", "jpeg": ".jpg", "webp": ".webp"}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


# ================================================================ auth

class Creds(BaseModel):
    email: str
    password: str


@app.get("/api/config")
def config():
    return {"llm_available": parse_llm.available(), "currency": CURRENCY, "locale": LOCALE}


@app.post("/api/auth/register")
def register(c: Creds, response: Response, db=Depends(get_db)):
    email = c.email.strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 200:
        raise HTTPException(400, "Please enter a valid email address.")
    if len(c.password) < 8:
        raise HTTPException(400, "Choose a password with at least 8 characters.")
    if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        raise HTTPException(409, "An account with this email already exists. Try signing in.")
    digest, salt = hash_password(c.password)
    uid = db.execute("INSERT INTO users(email,pw_hash,pw_salt) VALUES(?,?,?)", (email, digest, salt)).lastrowid
    seed_categories(db, uid)
    db.commit()
    start_session(db, response, uid)
    return {"id": uid, "email": email}


@app.post("/api/auth/login")
def login(c: Creds, request: Request, response: Response, db=Depends(get_db)):
    email = c.email.strip().lower()
    key = f"{email}|{request.client.host if request.client else ''}"
    throttle(key)
    row = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not row or not verify_password(c.password, row["pw_hash"], row["pw_salt"]):
        raise HTTPException(401, "That email and password don't match.")
    clear_throttle(key)
    start_session(db, response, row["id"])
    return {"id": row["id"], "email": row["email"]}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response, db=Depends(get_db)):
    end_session(db, request, response)
    return {"ok": True}


@app.get("/api/auth/session")
def auth_session(request: Request, db=Depends(get_db)):
    """Safe startup check: an anonymous visitor is not an API error."""
    try:
        user = current_user(request, db)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
        return {"authenticated": False, "user": None}
    return {"authenticated": True, "user": user}


@app.get("/api/auth/me")
def me(user=Depends(current_user)):
    return user


class ChangePassword(BaseModel):
    current_password: str
    new_password: str


@app.post("/api/auth/change-password")
def change_password(b: ChangePassword, response: Response, user=Depends(current_user), db=Depends(get_db)):
    row = db.execute("SELECT pw_hash,pw_salt FROM users WHERE id=?", (user["id"],)).fetchone()
    if not verify_password(b.current_password, row["pw_hash"], row["pw_salt"]):
        raise HTTPException(401, "Current password is incorrect.")
    update_password(db, user["id"], b.new_password)
    response.delete_cookie("spendflow_session", path="/")
    response.delete_cookie("tally_session", path="/")
    return {"ok": True, "message": "Password changed. Please sign in again."}


class ForgotPasswordIn(BaseModel):
    email: str


@app.post("/api/auth/forgot-password")
def forgot_password(b: ForgotPasswordIn, request: Request, db=Depends(get_db)):
    if not mail_recovery_available():
        raise HTTPException(503, "Email recovery is not configured on this server. Contact the server administrator.")
    ip = request.client.host if request.client else "unknown"
    throttle("forgot-ip|" + ip, limit=6, window=900)
    email = b.email.strip().lower()
    if len(email) <= 200 and EMAIL_RE.match(email):
        throttle("forgot-account|" + hashlib.sha256(email.encode()).hexdigest(), limit=4, window=900)
        code = issue_password_reset(db, email)
        if code:
            try:
                send_password_reset_email(email, code)
            except Exception:
                # Never reveal which accounts exist or leak the code on delivery errors.
                pass
    return {"ok": True, "message": "If that account exists, a recovery code has been sent."}


class PasswordResetIn(BaseModel):
    token: str
    new_password: str


@app.post("/api/auth/reset-password")
def reset_password(b: PasswordResetIn, request: Request, response: Response, db=Depends(get_db)):
    throttle("reset|" + (request.client.host if request.client else ""), limit=12, window=600)
    if len(b.new_password) < 12 or len(b.new_password) > 1024:
        raise HTTPException(400, "Choose a password of at least 12 characters.")
    if not redeem_password_reset(db, b.token, b.new_password):
        raise HTTPException(400, "That reset code is invalid or expired. Request another code.")
    response.delete_cookie("spendflow_session", path="/")
    response.delete_cookie("tally_session", path="/")
    return {"ok": True}


class DeleteAccount(BaseModel):
    password: str


def _delete_files(user_id: int) -> None:
    storage.delete_user_files(user_id)


@app.post("/api/auth/delete-account")
def delete_account(b: DeleteAccount, response: Response, user=Depends(current_user), db=Depends(get_db)):
    row = db.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    if not verify_password(b.password, row["pw_hash"], row["pw_salt"]):
        raise HTTPException(401, "That password isn't right.")
    db.execute("DELETE FROM users WHERE id=?", (user["id"],))
    db.commit()
    _delete_files(user["id"])
    response.delete_cookie("spendflow_session", path="/")
    return {"ok": True}


class Confirm(BaseModel):
    confirm: str


@app.post("/api/data/wipe")
def wipe_data(b: Confirm, user=Depends(current_user), db=Depends(get_db)):
    """Delete every statement, transaction and file, but keep the account, categories and budgets."""
    if b.confirm != "DELETE":
        raise HTTPException(400, 'Type DELETE to confirm.')
    uid = user["id"]
    db.execute("DELETE FROM transactions WHERE user_id=?", (uid,))
    db.execute("DELETE FROM statements WHERE user_id=?", (uid,))
    db.execute("DELETE FROM merchant_rules WHERE user_id=?", (uid,))
    db.execute("DELETE FROM import_exclusions WHERE user_id=?", (uid,))
    db.execute("DELETE FROM classification_rules WHERE user_id=?", (uid,))
    db.execute("DELETE FROM transaction_groups WHERE user_id=?", (uid,))
    db.commit()
    _delete_files(uid)
    return {"ok": True}


# ================================================================ People & Loans
class PersonIn(BaseModel):
    name: str = Field(min_length=1,max_length=80)

class UpiAliasIn(BaseModel):
    upi_id: str = Field(min_length=5,max_length=150)

class PersonLinkIn(BaseModel):
    txn_id: int
    role: str

@app.get("/api/people")
def list_people(user=Depends(current_user),db=Depends(get_db)):
    return people.overview(db,user["id"])

@app.post("/api/people")
def create_person(b:PersonIn,user=Depends(current_user),db=Depends(get_db)):
    name=b.name.strip()
    if not name: raise ValueError("Name required")
    cur=db.execute("INSERT INTO people(user_id,name) VALUES(?,?)",(user["id"],name))
    db.commit()
    return {"id":cur.lastrowid,"name":name}

@app.patch("/api/people/{pid}")
def rename_person(pid:int,b:PersonIn,user=Depends(current_user),db=Depends(get_db)):
    people.own(db,user["id"],pid)
    if not b.name.strip(): raise ValueError("Name required")
    db.execute("UPDATE people SET name=? WHERE id=?",(b.name.strip(),pid));db.commit()
    return {"ok":True}

@app.post("/api/people/{pid}/upi")
def add_person_upi(pid:int,b:UpiAliasIn,user=Depends(current_user),db=Depends(get_db)):
    people.own(db,user["id"],pid)
    upi=b.upi_id.strip().lower()
    if people.upi_ids(upi)!=[upi]: raise ValueError("Enter a valid UPI ID")
    try: db.execute("INSERT INTO people_upi(user_id,person_id,upi_id) VALUES(?,?,?)",(user["id"],pid,upi))
    except sqlite3.IntegrityError: raise ValueError("UPI ID is already linked to someone. Unlink it first.")
    db.commit();return {"ok":True}

@app.delete("/api/people/{pid}/upi/{alias_id}")
def remove_person_upi(pid:int,alias_id:int,user=Depends(current_user),db=Depends(get_db)):
    people.own(db,user["id"],pid)
    n=db.execute("DELETE FROM people_upi WHERE user_id=? AND person_id=? AND id=?",(user["id"],pid,alias_id)).rowcount
    if not n: raise LookupError("UPI ID not found.")
    db.commit();return {"ok":True}

@app.get("/api/people/{pid}/candidates")
def person_candidates(pid:int,user=Depends(current_user),db=Depends(get_db)):
    return people.candidates(db,user["id"],pid)

@app.get("/api/people/transaction/{tid}/suggestions")
def person_suggestions(tid:int,user=Depends(current_user),db=Depends(get_db)):
    return people.suggestions(db,user["id"],tid)

@app.post("/api/people/{pid}/transactions")
def link_person_transaction(pid:int,b:PersonLinkIn,user=Depends(current_user),db=Depends(get_db)):
    people.link(db,user["id"],pid,b.txn_id,b.role);db.commit()
    return {"ok":True}

@app.delete("/api/people/{pid}/transactions/{tid}")
def unlink_person_transaction(pid:int,tid:int,user=Depends(current_user),db=Depends(get_db)):
    people.own(db,user["id"],pid)
    row=db.execute("SELECT 1 FROM people_transactions WHERE user_id=? AND person_id=? AND txn_id=?",(user["id"],pid,tid)).fetchone()
    if not row: raise LookupError("Not linked to this person")
    people.unlink(db,user["id"],tid);db.commit();return {"ok":True}

@app.delete("/api/people/{pid}")
def delete_person(pid:int,user=Depends(current_user),db=Depends(get_db)):
    people.own(db,user["id"],pid)
    ids=[r["txn_id"] for r in db.execute("SELECT txn_id FROM people_transactions WHERE user_id=? AND person_id=?",(user["id"],pid))]
    for tid in ids: people.unlink(db,user["id"],tid)
    db.execute("DELETE FROM people WHERE id=? AND user_id=?",(pid,user["id"]));db.commit()
    return {"ok":True}

# ================================================================ accounts

class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    type: str = "bank"
    last4: str | None = Field(default=None, max_length=4)


def _own_account(db, uid: int, account_id: int):
    r = db.execute("SELECT * FROM accounts WHERE id=? AND user_id=?", (account_id, uid)).fetchone()
    if not r:
        raise LookupError("Account not found.")
    return r


@app.get("/api/accounts")
def list_accounts(user=Depends(current_user), db=Depends(get_db)):
    rows = db.execute(
        "SELECT a.*, (SELECT COUNT(*) FROM transactions t WHERE t.user_id=a.user_id AND t.account_id=a.id AND t.status!='staged') AS txn_count "
        "FROM accounts a WHERE a.user_id=? ORDER BY a.name", (user["id"],)).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/accounts")
def create_account(a: AccountIn, user=Depends(current_user), db=Depends(get_db)):
    t = a.type if a.type in ("bank", "upi", "card", "cash") else "bank"
    cur = db.execute("INSERT INTO accounts(user_id,name,type,last4) VALUES(?,?,?,?)",
                     (user["id"], a.name.strip(), t, (a.last4 or None)))
    db.commit()
    return dict(_own_account(db, user["id"], cur.lastrowid))


@app.patch("/api/accounts/{account_id}")
def update_account(account_id: int, a: AccountIn, user=Depends(current_user), db=Depends(get_db)):
    _own_account(db, user["id"], account_id)
    t = a.type if a.type in ("bank", "upi", "card", "cash") else "bank"
    db.execute("UPDATE accounts SET name=?, type=?, last4=? WHERE id=?", (a.name.strip(), t, a.last4 or None, account_id))
    db.commit()
    return dict(_own_account(db, user["id"], account_id))


@app.delete("/api/accounts/{account_id}")
def delete_account_row(account_id: int, user=Depends(current_user), db=Depends(get_db)):
    """Removes the account together with its statements and transactions."""
    _own_account(db, user["id"], account_id)
    for s in db.execute("SELECT stored_path FROM statements WHERE account_id=?", (account_id,)).fetchall():
        storage.delete_file(s["stored_path"], user["id"])
    db.execute("DELETE FROM transactions WHERE account_id=?", (account_id,))
    db.execute("DELETE FROM accounts WHERE id=?", (account_id,))
    db.commit()
    return {"ok": True}


# ================================================================ categories

class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    color: str = "#8E98A4"
    kind: str = "expense"


@app.get("/api/categories")
def list_categories(user=Depends(current_user), db=Depends(get_db)):
    rows = db.execute(
        "SELECT c.*, (SELECT COUNT(*) FROM transactions t WHERE t.category_id=c.id) AS uses FROM categories c "
        "WHERE c.user_id=? ORDER BY c.builtin DESC, c.sort, c.name", (user["id"],)).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/categories")
def create_category(c: CategoryIn, user=Depends(current_user), db=Depends(get_db)):
    name = c.name.strip()
    if db.execute("SELECT 1 FROM categories WHERE user_id=? AND lower(name)=lower(?)", (user["id"], name)).fetchone():
        raise HTTPException(409, f"You already have a category called “{name}”.")
    kind = c.kind if c.kind in ("expense", "income", "savings") else "expense"
    color = c.color if HEX.match(c.color) else "#8E98A4"
    nxt = db.execute("SELECT COALESCE(MAX(sort),0)+1 FROM categories WHERE user_id=?", (user["id"],)).fetchone()[0]
    cur = db.execute("INSERT INTO categories(user_id,name,color,kind,builtin,sort) VALUES(?,?,?,?,0,?)",
                     (user["id"], name, color, kind, nxt))
    db.commit()
    return dict(db.execute("SELECT * FROM categories WHERE id=?", (cur.lastrowid,)).fetchone())


@app.patch("/api/categories/{cid}")
def update_category(cid: int, c: CategoryIn, user=Depends(current_user), db=Depends(get_db)):
    cat = txns.get_category(db, user["id"], cid)
    if not cat:
        raise LookupError("Category not found.")
    color = c.color if HEX.match(c.color) else cat["color"]
    if cat["builtin"]:
        db.execute("UPDATE categories SET color=? WHERE id=?", (color, cid))
    else:
        name = c.name.strip()
        if db.execute("SELECT 1 FROM categories WHERE user_id=? AND lower(name)=lower(?) AND id!=?", (user["id"], name, cid)).fetchone():
            raise HTTPException(409, f"You already have a category called “{name}”.")
        kind = c.kind if c.kind in ("expense", "income", "savings") else cat["kind"]
        db.execute("UPDATE categories SET name=?, color=?, kind=? WHERE id=?", (name, color, kind, cid))
    db.commit()
    return dict(db.execute("SELECT * FROM categories WHERE id=?", (cid,)).fetchone())


@app.delete("/api/categories/{cid}")
def delete_category(cid: int, user=Depends(current_user), db=Depends(get_db)):
    cat = txns.get_category(db, user["id"], cid)
    if not cat:
        raise LookupError("Category not found.")
    if cat["builtin"]:
        raise HTTPException(400, "Built-in categories can't be deleted.")
    # Anything filed under it goes back to the review queue rather than silently vanishing.
    split_ids = [r["txn_id"] for r in db.execute("SELECT DISTINCT txn_id FROM splits WHERE category_id=?", (cid,))]
    for tid in split_ids:
        db.execute("DELETE FROM splits WHERE txn_id=?", (tid,))
    db.execute(
        "UPDATE transactions SET category_id=NULL, status='pending', reviewed_at=NULL, "
        "type=CASE WHEN transfer_pair_id IS NOT NULL THEN 'transfer' WHEN direction='credit' THEN 'income' ELSE 'expense' END "
        "WHERE user_id=? AND (category_id=? OR id IN (%s))" % (",".join("?" * len(split_ids)) or "NULL"),
        [user["id"], cid] + split_ids)
    db.execute("DELETE FROM categories WHERE id=?", (cid,))
    db.commit()
    return {"ok": True}


# ================================================================ importing

def _resolve_account(db, uid, account_id, new_name, new_type, res, cache: dict) -> int:
    if account_id:
        return _own_account(db, uid, account_id)["id"]
    if new_name:
        if "new" not in cache:
            t = new_type if new_type in ("bank", "upi", "card", "cash") else "bank"
            cache["new"] = db.execute("INSERT INTO accounts(user_id,name,type) VALUES(?,?,?)", (uid, new_name.strip()[:60], t)).lastrowid
        return cache["new"]
    name = res.account_name or ("Google Pay" if res.source_type == "gpay" else "Bank account")
    row = db.execute("SELECT id FROM accounts WHERE user_id=? AND name=? AND (last4 IS NULL OR ?='' OR last4=?)",
                     (uid, name, res.account_last4 or "", res.account_last4 or "")).fetchone()
    if row:
        return row["id"]
    return db.execute("INSERT INTO accounts(user_id,name,type,last4) VALUES(?,?,?,?)",
                      (uid, name, "upi" if res.source_type == "gpay" else "bank", res.account_last4)).lastrowid


@app.post("/api/imports/jobs", status_code=202)
def start_import_job(files: list[UploadFile] = File(...), account_id: int | None = Form(None),
                     new_account_name: str | None = Form(None), new_account_type: str = Form("bank"),
                     pdf_password: str | None = Form(None), use_ai: bool = Form(False),
                     user=Depends(current_user)):
    """Return immediately; parsing and staging run outside the HTTP request."""
    from . import import_jobs
    if not files or len(files) > MAX_FILES_PER_IMPORT:
        raise HTTPException(400, "Choose 1 to 10 files.")
    uploads = []
    for f in files:
        data = f.file.read(MAX_UPLOAD_BYTES + 1)
        uploads.append((Path(f.filename or "statement").name[:120], data))
    job_id = import_jobs.enqueue(user["id"], uploads, account_id,
                                 new_account_name, new_account_type, pdf_password, use_ai)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/imports/jobs/{job_id}")
def import_job_status(job_id: str, user=Depends(current_user), db=Depends(get_db)):
    row = db.execute("SELECT status,result FROM import_jobs WHERE id=? AND user_id=?",
                     (job_id, user["id"])).fetchone()
    if not row:
        raise LookupError("Import job not found.")
    return {"status": row["status"], **json.loads(row["result"] or "{}")}


@app.post("/api/imports")
def import_files(files: list[UploadFile] = File(...), account_id: int | None = Form(None),
                 new_account_name: str | None = Form(None), new_account_type: str = Form("bank"),
                 pdf_password: str | None = Form(None), use_ai: bool = Form(False),
                 user=Depends(current_user), db=Depends(get_db)):
    if not files:
        raise HTTPException(400, "Choose at least one file.")
    if len(files) > MAX_FILES_PER_IMPORT:
        raise HTTPException(400, f"Please upload at most {MAX_FILES_PER_IMPORT} files at a time.")
    uid = user["id"]
    user_dir = UPLOAD_DIR / str(uid)
    user_dir.mkdir(parents=True, exist_ok=True)
    cache: dict = {}
    results = []
    for f in files:
        name = Path(f.filename or "statement").name[:120]
        item = {"filename": name, "ok": False}
        results.append(item)
        data = f.file.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            item["error"] = f"This file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
            continue
        kind = sniff_kind(data[:16])
        if not kind:
            item["error"] = "Only PDF, PNG, JPG and WebP files are supported."
            continue
        sha = hashlib.sha256(data).hexdigest()
        dup = db.execute("SELECT id, status FROM statements WHERE user_id=? AND sha256=?", (uid, sha)).fetchone()
        if dup:
            item["error"] = ("You've already uploaded this exact file" +
                             (". Open it from Statements to confirm it." if dup["status"] == "preview"
                              else ". Delete it from Statements first if you want to import it again."))
            item["statement_id"] = dup["id"]
            continue
        path = user_dir / f"{uuid.uuid4().hex}{EXT[kind]}"
        path.write_bytes(data)
        try:
            res = parse_file(str(path), kind, pdf_password, use_ai)
        except PasswordRequired:
            path.unlink(missing_ok=True)
            item["needs_password"] = True
            item["error"] = ("The password didn't work. Please try again." if pdf_password
                             else "This PDF is password-protected. Enter its password to read it.")
            continue
        except UnreadableDocument as e:
            path.unlink(missing_ok=True)
            item["error"] = str(e)
            continue
        except Exception:
            path.unlink(missing_ok=True)
            item["error"] = "Something went wrong while reading this file. Try the PDF version, or a clearer image."
            continue
        if not res.rows:
            path.unlink(missing_ok=True)
            item["error"] = ("No transactions were found in this file. " +
                             ("Try again with “Use AI to read it” ticked." if parse_llm.available() and not use_ai
                              else "If it's a scan, a sharper image or the original PDF usually works better."))
            item["warnings"] = res.warnings
            continue
        aid = _resolve_account(db, uid, account_id, new_account_name, new_account_type, res, cache)
        stored_path = None
        try:
            stored_path = storage.persist(path, uid)
            sid = importing.create_statement(db, uid, aid, name, stored_path, sha, MIME[kind], res)
            db.commit()
        except Exception:
            db.rollback()
            if stored_path and stored_path.startswith("s3://"):
                try:
                    storage.delete_file(stored_path, uid)
                except Exception:
                    pass
            item["error"] = "Unable to securely save this statement. Please try again."
            continue
        finally:
            if storage.cloud_enabled():
                path.unlink(missing_ok=True)
        item.update(ok=True, statement_id=sid, count=len(res.rows), source_type=res.source_type, warnings=res.warnings)
    return {"results": results}


def _own_statement(db, uid: int, sid: int):
    r = db.execute("SELECT s.*, a.name AS account_name FROM statements s JOIN accounts a ON a.id=s.account_id "
                   "WHERE s.id=? AND s.user_id=?", (sid, uid)).fetchone()
    if not r:
        raise LookupError("Statement not found.")
    return r


@app.get("/api/imports/{sid}")
def import_preview(sid: int, user=Depends(current_user), db=Depends(get_db)):
    st = _own_statement(db, user["id"], sid)
    rows = []
    for r in db.execute("SELECT * FROM transactions WHERE statement_id=? AND user_id=? AND status='staged' ORDER BY id", (sid, user["id"])):
        d = {k: r[k] for k in ("id", "date", "description", "merchant", "amount_minor", "direction", "balance_minor", "dup_status")}
        d["flags"] = json.loads(r["flags"] or "[]")
        if r["dup_of"]:
            o = db.execute("SELECT t.date, t.description, a.name AS account_name FROM transactions t JOIN accounts a ON a.id=t.account_id "
                           "WHERE t.id=?", (r["dup_of"],)).fetchone()
            d["dup_info"] = dict(o) if o else None
        rows.append(d)
    return {
        "statement": {**{k: st[k] for k in ("id", "filename", "source_type", "parser", "status", "account_id", "account_name")},
                      "warnings": json.loads(st["warnings"])},
        "rows": rows,
        "summary": {
            "count": len(rows),
            "money_in": sum(r["amount_minor"] for r in rows if r["direction"] == "credit"),
            "money_out": sum(r["amount_minor"] for r in rows if r["direction"] == "debit"),
            "date_from": min((r["date"] for r in rows), default=None),
            "date_to": max((r["date"] for r in rows), default=None),
            "exact_duplicates": sum(1 for r in rows if r["dup_status"] == "exact"),
            "suspected_duplicates": sum(1 for r in rows if r["dup_status"] == "suspected"),
            "flagged": sum(1 for r in rows if [f for f in r["flags"] if not f.startswith("Read with OCR")]),
        },
    }


class StagedEdit(BaseModel):
    date: str | None = None
    description: str | None = Field(default=None, max_length=500)
    amount_minor: int | None = Field(default=None, gt=0, lt=10**13)
    direction: str | None = None
    dup_status: str | None = None   # "cleared" = import anyway, "restore" = treat as duplicate again


def _own_staged(db, uid: int, txn_id: int):
    r = db.execute("SELECT * FROM transactions WHERE id=? AND user_id=? AND status='staged'", (txn_id, uid)).fetchone()
    if not r:
        raise LookupError("That row isn't part of a pending import.")
    return r


@app.patch("/api/imports/rows/{txn_id}")
def edit_staged(txn_id: int, e: StagedEdit, user=Depends(current_user), db=Depends(get_db)):
    r = _own_staged(db, user["id"], txn_id)
    vals = {}
    if e.date is not None:
        iso = parse_date(e.date) or (e.date if re.fullmatch(r"\d{4}-\d{2}-\d{2}", e.date) else None)
        if not iso:
            raise HTTPException(400, "That date isn't valid.")
        vals["date"] = iso
    if e.description is not None:
        vals["description"] = e.description.strip()
        vals["merchant"] = extract_merchant(vals["description"])
        vals["merchant_key"] = merchant_key(vals["merchant"])
    if e.amount_minor is not None:
        vals["amount_minor"] = e.amount_minor
    if e.direction is not None:
        if e.direction not in ("debit", "credit"):
            raise HTTPException(400, "Direction must be money out or money in.")
        vals["direction"] = e.direction
        vals["type"] = "income" if e.direction == "credit" else "expense"
    if e.dup_status == "cleared":
        vals["dup_status"], vals["dup_of"] = "cleared", None
    if vals:
        flags = [f for f in json.loads(r["flags"] or "[]") if not f.startswith(("Doesn't match", "Debit/credit"))]
        sets = ", ".join(f"{k}=?" for k in vals)
        db.execute(f"UPDATE transactions SET {sets}, flags=? WHERE id=?", [*vals.values(), json.dumps(flags), txn_id])
        db.commit()
    return {"ok": True}


@app.delete("/api/imports/rows/{txn_id}")
def delete_staged(txn_id: int, user=Depends(current_user), db=Depends(get_db)):
    r = _own_staged(db, user["id"], txn_id)
    db.execute("DELETE FROM transactions WHERE id=?", (txn_id,))
    importing.refresh_statement_meta(db, r["statement_id"])
    db.commit()
    return {"ok": True}


class StagedNew(BaseModel):
    date: str
    description: str = Field(max_length=500)
    amount_minor: int = Field(gt=0, lt=10**13)
    direction: str


@app.post("/api/imports/{sid}/rows")
def add_staged(sid: int, n: StagedNew, user=Depends(current_user), db=Depends(get_db)):
    st = _own_statement(db, user["id"], sid)
    if st["status"] != "preview":
        raise HTTPException(400, "This statement was already confirmed.")
    iso = parse_date(n.date) or (n.date if re.fullmatch(r"\d{4}-\d{2}-\d{2}", n.date) else None)
    if not iso or n.direction not in ("debit", "credit"):
        raise HTTPException(400, "Please enter a valid date and choose money in or out.")
    m = extract_merchant(n.description)
    tid = importing.insert_staged_row(db, user["id"], st["account_id"], sid, {
        "date": iso, "description": n.description.strip(), "amount_minor": n.amount_minor, "direction": n.direction,
        "merchant": m, "merchant_key": merchant_key(m), "flags": ["Added by you"]})
    importing.refresh_statement_meta(db, sid)
    db.commit()
    return {"id": tid}


@app.post("/api/imports/{sid}/commit")
def commit_import(sid: int, user=Depends(current_user), db=Depends(get_db)):
    _own_statement(db, user["id"], sid)
    return importing.commit_statement(db, user["id"], sid)



# ================================================================ transaction tags

class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = "custom"


class TagAssignment(BaseModel):
    tag_ids: list[int] = Field(default_factory=list, max_length=20)


@app.get("/api/tags")
def list_tags(user=Depends(current_user), db=Depends(get_db)):
    uid = user["id"]
    rows = db.execute(
        "SELECT g.id,g.name,g.kind,COUNT(t.id) AS transaction_count,"
        "COALESCE(SUM(CASE WHEN t.type='expense' AND t.direction='debit' "
        "AND t.status!='staged' AND t.removed_at IS NULL "
        "AND (t.dup_status IS NULL OR t.dup_status='cleared') THEN t.amount_minor ELSE 0 END),0) AS expense_minor "
        "FROM tags g LEFT JOIN transaction_tags tt ON tt.tag_id=g.id "
        "LEFT JOIN transactions t ON t.id=tt.txn_id AND t.user_id=g.user_id "
        "WHERE g.user_id=? GROUP BY g.id,g.name,g.kind ORDER BY g.kind,g.name",
        (uid,)).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/tags")
def create_tag(body: TagCreate, user=Depends(current_user), db=Depends(get_db)):
    name = body.name.strip()
    if not name or body.kind not in ("trip", "person", "custom"):
        raise HTTPException(400, "Choose a tag name and valid type.")
    existing = db.execute("SELECT id,name,kind FROM tags WHERE user_id=? AND kind=? AND lower(name)=lower(?)",
                          (user["id"], body.kind, name)).fetchone()
    if existing:
        return dict(existing)
    cur = db.execute("INSERT INTO tags(user_id,kind,name) VALUES(?,?,?)", (user["id"], body.kind, name))
    tag_id = cur.lastrowid
    db.commit()
    return {"id": tag_id, "name": name, "kind": body.kind}


@app.get("/api/transactions/{txn_id}/tags")
def get_transaction_tags(txn_id: int, user=Depends(current_user), db=Depends(get_db)):
    if not db.execute("SELECT 1 FROM transactions WHERE id=? AND user_id=? AND status!='staged'",
                      (txn_id, user["id"])).fetchone():
        raise LookupError("Transaction not found.")
    return [dict(r) for r in db.execute(
        "SELECT g.id,g.name,g.kind FROM tags g JOIN transaction_tags tt ON tt.tag_id=g.id "
        "WHERE tt.txn_id=? AND g.user_id=? ORDER BY g.kind,g.name",
        (txn_id, user["id"]))]


@app.put("/api/transactions/{txn_id}/tags")
def set_transaction_tags(txn_id: int, body: TagAssignment, user=Depends(current_user), db=Depends(get_db)):
    uid = user["id"]
    if not db.execute("SELECT 1 FROM transactions WHERE id=? AND user_id=? AND status!='staged'",
                      (txn_id, uid)).fetchone():
        raise LookupError("Transaction not found.")
    ids = sorted(set(body.tag_ids))
    if ids:
        valid = db.execute(
            "SELECT id FROM tags WHERE user_id=? AND id IN (" + ",".join("?" * len(ids)) + ")",
            [uid, *ids]).fetchall()
        if len(valid) != len(ids):
            raise HTTPException(400, "One or more tags were not found.")
    db.execute("DELETE FROM transaction_tags WHERE txn_id=?", (txn_id,))
    for tag_id in ids:
        db.execute("INSERT INTO transaction_tags(txn_id,tag_id) VALUES(?,?)", (txn_id, tag_id))
    db.commit()
    return {"tag_ids": ids}


@app.get("/api/tags/{tag_id}/transactions")
def tag_transactions(tag_id: int, user=Depends(current_user), db=Depends(get_db)):
    tag = db.execute("SELECT id,name,kind FROM tags WHERE id=? AND user_id=?", (tag_id,user["id"])).fetchone()
    if not tag:
        raise LookupError("Tag not found.")
    rows = db.execute(
        "SELECT t.id,t.date,t.amount_minor,t.direction,t.type,t.merchant,t.description,a.name AS account_name "
        "FROM transaction_tags tt JOIN transactions t ON t.id=tt.txn_id "
        "JOIN accounts a ON a.id=t.account_id "
        "WHERE tt.tag_id=? AND t.user_id=? AND t.status!='staged' AND t.removed_at IS NULL "
        "ORDER BY t.date DESC,t.id DESC LIMIT 1000", (tag_id,user["id"])).fetchall()
    return {"tag": dict(tag), "transactions": [dict(r) for r in rows]}


@app.get("/api/statements")
def list_statements(user=Depends(current_user), db=Depends(get_db)):
    rows = db.execute(
        "SELECT s.id, s.filename, s.source_type, s.parser, s.status, s.date_from, s.date_to, s.txn_count, s.created_at, "
        "s.warnings, a.name AS account_name, "
        "(SELECT COUNT(*) FROM transactions t WHERE t.statement_id=s.id AND t.status='categorized') AS reviewed "
        "FROM statements s JOIN accounts a ON a.id=s.account_id WHERE s.user_id=? ORDER BY s.id DESC", (user["id"],)).fetchall()
    return [{**dict(r), "warnings": json.loads(r["warnings"])} for r in rows]


@app.get("/api/statements/{sid}/file")
def statement_file(sid: int, user=Depends(current_user), db=Depends(get_db)):
    st = _own_statement(db, user["id"], sid)
    try:
        kind, file = storage.get_file(st["stored_path"], user["id"])
    except (OSError, ValueError):
        raise LookupError("The original file is no longer stored.")
    if kind == "local":
        return FileResponse(file, media_type=st["mime"] or "application/octet-stream", filename=st["filename"])
    from urllib.parse import quote
    return StreamingResponse(storage.iter_body(file), media_type=st["mime"] or "application/octet-stream",
                             headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(st["filename"]),
                                      "Cache-Control": "private, no-store"})


@app.delete("/api/statements/{sid}")
def delete_statement(sid: int, transactions: bool = False, user=Depends(current_user), db=Depends(get_db)):
    """Delete the uploaded file. With transactions=true also delete what was imported from it."""
    st = _own_statement(db, user["id"], sid)
    if st["status"] == "preview" or transactions:
        ids = [r["id"] for r in db.execute("SELECT id FROM transactions WHERE statement_id=?", (sid,))]
        if ids:
            marks = ",".join("?" * len(ids))
            db.execute(f"UPDATE transactions SET transfer_pair_id=NULL WHERE transfer_pair_id IN ({marks})", ids)
            db.execute(f"DELETE FROM transactions WHERE id IN ({marks})", ids)
    storage.delete_file(st["stored_path"], user["id"])
    db.execute("DELETE FROM statements WHERE id=?", (sid,))
    db.commit()
    return {"ok": True}


# ================================================================ duplicates

@app.get("/api/duplicates")
def duplicates(user=Depends(current_user), db=Depends(get_db)):
    return importing.duplicate_pairs(db, user["id"])


class DupAction(BaseModel):
    action: str   # keep | delete


@app.post("/api/duplicates/{txn_id}/resolve")
def resolve_duplicate(txn_id: int, b: DupAction, user=Depends(current_user), db=Depends(get_db)):
    r = db.execute("SELECT id FROM transactions WHERE id=? AND user_id=? AND dup_status='suspected'", (txn_id, user["id"])).fetchone()
    if not r:
        raise LookupError("That transaction isn't flagged as a duplicate.")
    if b.action == "keep":
        db.execute("UPDATE transactions SET dup_status='cleared' WHERE id=?", (txn_id,))
    elif b.action == "delete":
        db.execute("UPDATE transactions SET transfer_pair_id=NULL WHERE transfer_pair_id=?", (txn_id,))
        db.execute("DELETE FROM transactions WHERE id=?", (txn_id,))
    else:
        raise HTTPException(400, "Unknown action.")
    db.commit()
    return {"ok": True}


@app.post("/api/duplicates/resolve-all")
def resolve_all_duplicates(b: DupAction, user=Depends(current_user), db=Depends(get_db)):
    ids = [r["id"] for r in db.execute("SELECT id FROM transactions WHERE user_id=? AND dup_status='suspected' AND status!='staged'", (user["id"],))]
    for i in ids:
        resolve_duplicate(i, b, user, db)
    return {"changed": len(ids)}


# ================================================================ review flow

class SplitIn(BaseModel):
    category_id: int
    amount_minor: int
    note: str | None = None


class CategorizeIn(BaseModel):
    category_id: int | None = None
    note: str | None = Field(default=None, max_length=500)
    recurring: bool | None = None
    recurring_freq: str | None = None
    type: str | None = None
    apply_similar: bool = False
    remember: bool = False
    splits: list[SplitIn] | None = None


def _review_state(db, uid: int, scope: str, order: str = 'desc') -> dict:
    return {"item": txns.next_item(db, uid, scope, order), "progress": txns.progress(db, uid), "scope": scope}


@app.get("/api/review/next")
def review_next(scope: str = "pending", order: str = "desc", user=Depends(current_user), db=Depends(get_db)):
    return _review_state(db, user["id"], "skipped" if scope == "skipped" else "pending", order)


@app.post("/api/review/{txn_id}/categorize")
def review_categorize(txn_id: int, b: CategorizeIn, scope: str = "pending", order: str = "desc", user=Depends(current_user), db=Depends(get_db)):
    res = txns.apply_category(db, user["id"], txn_id, b.model_dump(exclude_unset=True))
    scope = "skipped" if scope == "skipped" else "pending"
    return {**{k: res[k] for k in ("undo", "applied_similar", "partner_confirmed")}, **_review_state(db, user["id"], scope, order)}


@app.post("/api/review/{txn_id}/skip")
def review_skip(txn_id: int, scope: str = "pending", order: str = "desc", user=Depends(current_user), db=Depends(get_db)):
    res = txns.skip_txn(db, user["id"], txn_id)
    scope = "skipped" if scope == "skipped" else "pending"
    return {"undo": res["undo"], **_review_state(db, user["id"], scope, order)}


class RestoreIn(BaseModel):
    undo: list[dict]


@app.post("/api/review/restore")
def review_restore(b: RestoreIn, scope: str = "pending", order: str = "desc", user=Depends(current_user), db=Depends(get_db)):
    n = txns.restore(db, user["id"], b.undo)
    db.commit()
    state = _review_state(db, user["id"], "skipped" if scope == "skipped" else "pending", order)
    first = b.undo[0].get("id") if b.undo else None
    if isinstance(first, int):
        item = txns.item_for(db, user["id"], first)
        if item:
            state["item"] = item
    return {"restored": n, **state}


# ================================================================ transactions

@app.get("/api/transactions")
def list_transactions(request: Request, user=Depends(current_user), db=Depends(get_db)):
    q = dict(request.query_params)
    try:
        return txns.search(db, user["id"], q)
    except (ValueError, TypeError):
        raise HTTPException(400, "One of the filters isn't valid.")


@app.get("/api/transactions/{txn_id}")
def get_transaction(txn_id: int, user=Depends(current_user), db=Depends(get_db)):
    t = txns.get_txn(db, user["id"], txn_id)
    if not t or t.get("removed_at"):
        raise LookupError("Transaction not found.")
    return {"txn": t, "suggestion": txns.suggest(db, user["id"], t)}


class TxnEdit(BaseModel):
    category_id: int | None = None
    splits: list[SplitIn] | None = None
    note: str | None = Field(default=None, max_length=500)
    recurring: bool | None = None
    recurring_freq: str | None = None
    type: str | None = None
    merchant: str | None = Field(default=None, max_length=80)
    date: str | None = None
    amount_minor: int | None = Field(default=None, gt=0, lt=10**13)
    direction: str | None = None
    send_to_review: bool = False
    remember: bool = False
    remember: bool = False


@app.patch("/api/transactions/{txn_id}")
def edit_transaction(txn_id: int, e: TxnEdit, user=Depends(current_user), db=Depends(get_db)):
    uid = user["id"]
    body = e.model_dump(exclude_unset=True)
    row = db.execute("SELECT * FROM transactions WHERE id=? AND user_id=? AND status!='staged'", (txn_id, uid)).fetchone()
    if not row:
        raise LookupError("Transaction not found.")
    undo: list[dict] = []

    if body.get("send_to_review"):
        undo = txns.bulk(db, uid, [txn_id], "pending", {})["undo"]
        return {"txn": txns.get_txn(db, uid, txn_id), "undo": undo}

    if db.execute("SELECT 1 FROM (SELECT txn_id FROM transaction_group_members UNION ALL SELECT txn_id FROM flow_group_members UNION ALL SELECT txn_id FROM people_transactions) WHERE txn_id=?", (txn_id,)).fetchone() and (
        ("category_id" in body and body["category_id"] != row["category_id"]) or body.get("splits") or
        ("type" in body and body["type"] != row["type"]) or
        ("direction" in body and body["direction"] != row["direction"]) or
        ("amount_minor" in body and body["amount_minor"] != row["amount_minor"])):
        raise HTTPException(400, "Unlink this transaction from its group before changing its accounting details.")
    # field corrections
    vals = {}
    if "merchant" in body and body["merchant"] is not None:
        m = body["merchant"].strip()
        if m:
            vals["merchant"], vals["merchant_key"] = m, merchant_key(m)
    if "date" in body and body["date"]:
        iso = parse_date(body["date"]) or (body["date"] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", body["date"]) else None)
        if not iso:
            raise HTTPException(400, "That date isn't valid.")
        vals["date"] = iso
    if "amount_minor" in body or "direction" in body:
        if db.execute("SELECT 1 FROM splits WHERE txn_id=?", (txn_id,)).fetchone() and not body.get("splits"):
            raise HTTPException(400, "Remove the split first, then change the amount.")
        if "amount_minor" in body:
            vals["amount_minor"] = body["amount_minor"]
        if "direction" in body:
            if body["direction"] not in ("debit", "credit"):
                raise HTTPException(400, "Direction must be money out or money in.")
            vals["direction"] = body["direction"]
    if vals:
        undo.append(txns.snapshot(db, txn_id))
        db.execute(f"UPDATE transactions SET {', '.join(f'{k}=?' for k in vals)} WHERE id=?", [*vals.values(), txn_id])

    if "category_id" in body or body.get("splits"):
        payload = {k: body[k] for k in ("category_id", "splits", "note", "recurring", "recurring_freq", "type", "remember") if k in body}
        res = txns.apply_category(db, uid, txn_id, payload)
        undo = (undo + res["undo"]) if undo else res["undo"]
    else:
        sets, args = [], []
        if "note" in body:
            sets.append("note=?")
            args.append(txns.clean_note(body["note"]))
        if "recurring" in body:
            sets += ["recurring=?", "recurring_freq=?"]
            args += [1 if body["recurring"] else 0,
                     (body.get("recurring_freq") if body.get("recurring_freq") in txns.FREQS else row["recurring_freq"] or "monthly") if body["recurring"] else None]
        if "type" in body and body["type"] in txns.TYPES:
            sets.append("type=?")
            args.append(body["type"])
        if sets:
            if not undo:
                undo.append(txns.snapshot(db, txn_id))
            db.execute(f"UPDATE transactions SET {', '.join(sets)} WHERE id=?", [*args, txn_id])
    if body.get("remember") and row["merchant_key"]:
        fresh = db.execute("SELECT * FROM transactions WHERE id=?", (txn_id,)).fetchone()
        if fresh["category_id"]:
            ledger.remember(db, uid, fresh, fresh["category_id"], fresh["type"])
    db.commit()
    return {"txn": txns.get_txn(db, uid, txn_id), "undo": undo}


class BulkIn(BaseModel):
    ids: list[int]
    action: str
    category_id: int | None = None
    type: str | None = None


@app.post("/api/transactions/bulk")
def bulk_transactions(b: BulkIn, user=Depends(current_user), db=Depends(get_db)):
    return txns.bulk(db, user["id"], b.ids, b.action, b.model_dump(exclude={"ids", "action"}))


@app.post("/api/transactions/restore")
def restore_transactions(b: RestoreIn, user=Depends(current_user), db=Depends(get_db)):
    n = txns.restore(db, user["id"], b.undo)
    db.commit()
    return {"restored": n}


@app.delete("/api/transactions/{txn_id}")
def delete_transaction(txn_id: int, user=Depends(current_user), db=Depends(get_db)):
    if not db.execute("SELECT 1 FROM transactions WHERE id=? AND user_id=?", (txn_id, user["id"])).fetchone():
        raise LookupError("Transaction not found.")
    db.execute("UPDATE transactions SET removed_at=datetime('now') WHERE id=? AND user_id=?", (txn_id, user["id"]))
    db.commit()
    return {"ok": True}


@app.get("/api/export.csv")
def export_csv(user=Depends(current_user), db=Depends(get_db)):
    rows = db.execute(
        txns.SELECT_TXN + f" WHERE t.user_id=? AND {txns.ACTIVE} ORDER BY t.date, t.id", (user["id"],)).fetchall()

    def safe(v):
        s = "" if v is None else str(v)
        return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s   # spreadsheet formula injection

    def gen():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["date", "account", "merchant", "description", "money_in", "money_out", "type", "category", "note", "recurring", "status"])
        yield buf.getvalue()
        for r in rows:
            buf.seek(0), buf.truncate()
            amt = r["amount_minor"] / 100
            w.writerow([r["date"], safe(r["account_name"]), safe(r["merchant"]), safe(r["description"]),
                        amt if r["direction"] == "credit" else "", amt if r["direction"] == "debit" else "",
                        r["type"], safe(r["category_name"] or ("Split" if r["split_count"] else "")), safe(r["note"]),
                        "yes" if r["recurring"] else "", r["status"]])
            yield buf.getvalue()

    return StreamingResponse(gen(), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="spendflow-transactions.csv"'})



# ================================================================ persistent rules and linked cash flows

class ExclusionIn(BaseModel):
    confirmed: bool = False

@app.post("/api/transactions/{txn_id}/exclude")
def exclude_transaction(txn_id: int, b: ExclusionIn, user=Depends(current_user), db=Depends(get_db)):
    if not b.confirmed:
        raise HTTPException(400, "Confirm the exclusion rule before saving.")
    ledger.save_exclusion(db, user["id"], txn_id)
    # Preserve the original imported financial record; hide it without altering its bank balance.
    db.execute("UPDATE transactions SET removed_at=datetime('now') WHERE id=? AND user_id=?", (txn_id, user["id"]))
    db.commit()
    return {"ok": True}

@app.get("/api/rules")
def list_rules(user=Depends(current_user), db=Depends(get_db)):
    return ledger.rules(db, user["id"])

@app.delete("/api/rules/{kind}/{rule_id}")
def delete_rule(kind: str, rule_id: int, user=Depends(current_user), db=Depends(get_db)):
    table = {"exclusion":"import_exclusions","classification":"classification_rules"}.get(kind)
    if not table:
        raise HTTPException(400, "Unknown rule kind.")
    changed = db.execute(f"DELETE FROM {table} WHERE id=? AND user_id=?", (rule_id,user["id"])).rowcount
    db.commit()
    if not changed:
        raise LookupError("Rule not found.")
    return {"ok": True}

class GroupIn(BaseModel):
    name: str = Field(min_length=1,max_length=100)
    kind: str
    ids: list[int] = Field(min_length=1,max_length=100)

class MemberIn(BaseModel):
    ids: list[int] = Field(min_length=1,max_length=100)

@app.get("/api/groups")
def list_groups(user=Depends(current_user), db=Depends(get_db)):
    return ledger.list_groups(db, user["id"])

@app.get("/api/transactions/{txn_id}/matches")
def transaction_matches(txn_id: int, user=Depends(current_user), db=Depends(get_db)):
    return ledger.suggestions(db, user["id"], txn_id)

@app.post("/api/groups")
def create_group(b: GroupIn, user=Depends(current_user), db=Depends(get_db)):
    if b.kind not in ("loan","repayment","pass_through","transfer"):
        raise HTTPException(400, "Unknown group kind.")
    cur = db.execute("INSERT INTO transaction_groups(user_id,name,kind) VALUES(?,?,?)",
                     (user["id"],b.name.strip(),b.kind))
    ledger.add_members(db,user["id"],cur.lastrowid,b.ids)
    db.commit()
    return {"id":cur.lastrowid}

@app.post("/api/groups/{group_id}/members")
def link_group(group_id: int, b: MemberIn, user=Depends(current_user), db=Depends(get_db)):
    changed=ledger.add_members(db,user["id"],group_id,b.ids)
    db.commit()
    return {"changed":changed}

@app.delete("/api/groups/{group_id}/members/{txn_id}")
def unlink_group(group_id: int, txn_id: int, user=Depends(current_user), db=Depends(get_db)):
    ledger.unlink(db,user["id"],group_id,txn_id)
    db.commit()
    return {"ok":True}

@app.delete("/api/groups/{group_id}")
def remove_group(group_id: int, user=Depends(current_user), db=Depends(get_db)):
    if not db.execute("SELECT 1 FROM transaction_groups WHERE id=? AND user_id=?",(group_id,user["id"])).fetchone():
        raise LookupError("Group not found.")
    ids=[r["txn_id"] for r in db.execute("SELECT txn_id FROM transaction_group_members WHERE group_id=?",(group_id,))]
    for tid in ids:
        ledger.unlink(db,user["id"],group_id,tid)
    db.execute("DELETE FROM transaction_groups WHERE id=?",(group_id,))
    db.commit()
    return {"ok":True}

class ManualTxn(BaseModel):
    account_id: int
    date: str
    amount_minor: int = Field(gt=0,lt=10**13)
    direction: str
    description: str = Field(min_length=1,max_length=500)

@app.post("/api/transactions")
def add_transaction(b: ManualTxn, user=Depends(current_user), db=Depends(get_db)):
    uid=user["id"]
    _own_account(db,uid,b.account_id)
    try:
        iso=date.fromisoformat(b.date).isoformat()
    except ValueError:
        raise HTTPException(400,"Invalid date.")
    if b.direction not in ("debit","credit"):
        raise HTTPException(400,"Invalid direction.")
    merchant=extract_merchant(b.description)
    cur=db.execute("INSERT INTO transactions(user_id,account_id,date,amount_minor,direction,type,description,merchant,merchant_key,status,flags) "
        "VALUES(?,?,?,?,?,?,?,?,?,'pending','[]')",
        (uid,b.account_id,iso,b.amount_minor,b.direction,"income" if b.direction=="credit" else "expense",
         b.description,merchant,merchant_key(merchant)))
    db.commit()
    return {"txn":txns.get_txn(db,uid,cur.lastrowid)}



# ================================================================ saved rules and recoverable removals

class ExcludeIn(BaseModel):
    transaction_id: int

@app.get("/api/exclusions")
def exclusions(user=Depends(current_user), db=Depends(get_db)):
    return [dict(r) for r in db.execute("SELECT e.*, a.name AS account_name FROM exclusion_rules e JOIN accounts a ON a.id=e.account_id WHERE e.user_id=? ORDER BY e.id DESC", (user["id"],))]

@app.post("/api/exclusions")
def add_exclusion(b: ExcludeIn, user=Depends(current_user), db=Depends(get_db)):
    t = db.execute("SELECT * FROM transactions WHERE user_id=? AND id=? AND status!='staged'", (user["id"],b.transaction_id)).fetchone()
    if not t or len(t["merchant_key"]) < 3:
        raise ValueError("Choose a transaction with a distinct merchant before creating an exclusion.")
    db.execute("INSERT OR IGNORE INTO exclusion_rules(user_id,account_id,merchant_key,direction,amount_minor) VALUES(?,?,?,?,?)", (user["id"],t["account_id"],t["merchant_key"],t["direction"],t["amount_minor"]))
    db.execute("UPDATE transactions SET removed_at=datetime('now') WHERE id=?", (b.transaction_id,))
    db.commit()
    return {"ok": True}

@app.delete("/api/exclusions/{rule_id}")
def delete_exclusion(rule_id: int, user=Depends(current_user), db=Depends(get_db)):
    if not db.execute("SELECT 1 FROM exclusion_rules WHERE id=? AND user_id=?", (rule_id,user["id"])).fetchone():
        raise LookupError("Rule not found")
    db.execute("DELETE FROM exclusion_rules WHERE id=? AND user_id=?", (rule_id,user["id"]))
    db.commit()
    return {"ok": True}

@app.get("/api/classification-rules")
def classification_rules(user=Depends(current_user), db=Depends(get_db)):
    return [dict(r) for r in db.execute("SELECT r.*,c.name AS category_name FROM classification_rules r JOIN categories c ON c.id=r.category_id WHERE r.user_id=? ORDER BY r.id DESC", (user["id"],))]

class RuleEdit(BaseModel):
    category_id: int
    type: str

@app.patch("/api/classification-rules/{rule_id}")
def edit_classification_rule(rule_id: int, b: RuleEdit, user=Depends(current_user), db=Depends(get_db)):
    if b.type not in txns.TYPES or not txns.get_category(db,user["id"],b.category_id):
        raise ValueError("Choose a valid type and category")
    result=db.execute("UPDATE classification_rules SET category_id=?,type=? WHERE id=? AND user_id=?", (b.category_id,b.type,rule_id,user["id"]))
    if not result.rowcount:
        raise LookupError("Rule not found")
    db.commit()
    return {"ok":True}

@app.delete("/api/classification-rules/{rule_id}")
def delete_classification_rule(rule_id: int, user=Depends(current_user), db=Depends(get_db)):
    result=db.execute("DELETE FROM classification_rules WHERE id=? AND user_id=?", (rule_id,user["id"]))
    if not result.rowcount:
        raise LookupError("Rule not found")
    db.commit()
    return {"ok":True}

@app.post("/api/transactions/{txn_id}/restore")
def restore_removed_transaction(txn_id: int, user=Depends(current_user), db=Depends(get_db)):
    result=db.execute("UPDATE transactions SET removed_at=NULL, excluded_rule_id=NULL WHERE id=? AND user_id=?", (txn_id,user["id"]))
    if not result.rowcount:
        raise LookupError("Transaction not found")
    db.commit()
    return {"ok":True}

# ================================================================ dashboard, budgets, goals, recurring

@app.get("/api/dashboard")
def dashboard(month: str | None = None, user=Depends(current_user), db=Depends(get_db)):
    if month is not None and not re.fullmatch(r"\d{4}-\d{2}", month):
        raise HTTPException(400, "Month must look like 2026-10.")
    return analytics.dashboard(db, user["id"], month)


@app.get("/api/budgets")
def get_budgets(month: str | None = None, user=Depends(current_user), db=Depends(get_db)):
    m = analytics.pick_month(db, user["id"], month) or date.today().strftime("%Y-%m")
    return {"month": m, "months": analytics.month_list(db, user["id"]), **analytics.budgets_status(db, user["id"], m)}


class BudgetIn(BaseModel):
    category_id: int | None = None      # null = overall monthly limit
    limit_minor: int | None = Field(default=None, ge=0, lt=10**13)   # null or 0 removes it


@app.put("/api/budgets")
def put_budget(b: BudgetIn, user=Depends(current_user), db=Depends(get_db)):
    uid = user["id"]
    if b.category_id is not None and not txns.get_category(db, uid, b.category_id):
        raise LookupError("Category not found.")
    existing = db.execute("SELECT id FROM budgets WHERE user_id=? AND category_id IS ?", (uid, b.category_id)).fetchone()
    if not b.limit_minor:
        if existing:
            db.execute("DELETE FROM budgets WHERE id=?", (existing["id"],))
    elif existing:
        db.execute("UPDATE budgets SET limit_minor=? WHERE id=?", (b.limit_minor, existing["id"]))
    else:
        db.execute("INSERT INTO budgets(user_id,category_id,limit_minor) VALUES(?,?,?)", (uid, b.category_id, b.limit_minor))
    db.commit()
    return {"ok": True}


class GoalIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    target_minor: int = Field(gt=0, lt=10**13)
    saved_minor: int = Field(default=0, ge=0, lt=10**13)
    deadline: str | None = None


def _own_goal(db, uid, gid):
    g = db.execute("SELECT * FROM goals WHERE id=? AND user_id=?", (gid, uid)).fetchone()
    if not g:
        raise LookupError("Goal not found.")
    return g


@app.get("/api/goals")
def list_goals(user=Depends(current_user), db=Depends(get_db)):
    return [dict(g) for g in db.execute("SELECT * FROM goals WHERE user_id=? ORDER BY id", (user["id"],))]


@app.post("/api/goals")
def create_goal(g: GoalIn, user=Depends(current_user), db=Depends(get_db)):
    dl = g.deadline if g.deadline and re.fullmatch(r"\d{4}-\d{2}-\d{2}", g.deadline) else None
    cur = db.execute("INSERT INTO goals(user_id,name,target_minor,saved_minor,deadline) VALUES(?,?,?,?,?)",
                     (user["id"], g.name.strip(), g.target_minor, g.saved_minor, dl))
    db.commit()
    return dict(_own_goal(db, user["id"], cur.lastrowid))


@app.patch("/api/goals/{gid}")
def update_goal(gid: int, g: GoalIn, user=Depends(current_user), db=Depends(get_db)):
    _own_goal(db, user["id"], gid)
    dl = g.deadline if g.deadline and re.fullmatch(r"\d{4}-\d{2}-\d{2}", g.deadline) else None
    db.execute("UPDATE goals SET name=?, target_minor=?, saved_minor=?, deadline=? WHERE id=?",
               (g.name.strip(), g.target_minor, g.saved_minor, dl, gid))
    db.commit()
    return dict(_own_goal(db, user["id"], gid))


class Contribution(BaseModel):
    amount_minor: int = Field(gt=-10**13, lt=10**13)


@app.post("/api/goals/{gid}/contribute")
def contribute(gid: int, c: Contribution, user=Depends(current_user), db=Depends(get_db)):
    g = _own_goal(db, user["id"], gid)
    db.execute("UPDATE goals SET saved_minor=MAX(0, ?) WHERE id=?", (g["saved_minor"] + c.amount_minor, gid))
    db.commit()
    return dict(_own_goal(db, user["id"], gid))


@app.delete("/api/goals/{gid}")
def delete_goal(gid: int, user=Depends(current_user), db=Depends(get_db)):
    _own_goal(db, user["id"], gid)
    db.execute("DELETE FROM goals WHERE id=?", (gid,))
    db.commit()
    return {"ok": True}


@app.get("/api/recurring")
def get_recurring(user=Depends(current_user), db=Depends(get_db)):
    return {**analytics.recurring_overview(db, user["id"]), "detected": analytics.detect_recurring(db, user["id"])}


class RecurringIn(BaseModel):
    merchant_key: str
    frequency: str = "monthly"


@app.post("/api/recurring/track")
def track_recurring(b: RecurringIn, user=Depends(current_user), db=Depends(get_db)):
    freq = b.frequency if b.frequency in txns.FREQS else "monthly"
    db.execute(f"UPDATE transactions SET recurring=1, recurring_freq=? WHERE user_id=? AND merchant_key=? AND {txns.ACTIVE.replace('t.', '')}",
               (freq, user["id"], b.merchant_key))
    db.commit()
    return {"ok": True}


@app.post("/api/recurring/stop")
def stop_recurring(b: RecurringIn, user=Depends(current_user), db=Depends(get_db)):
    db.execute("UPDATE transactions SET recurring=0, recurring_freq=NULL WHERE user_id=? AND (merchant_key=? OR ('id' || id)=?)",
               (user["id"], b.merchant_key, b.merchant_key))
    db.commit()
    return {"ok": True}



# ================================================================ linked non-personal flows

class FlowIn(BaseModel):
    kind: str
    transaction_ids: list[int]

@app.get("/api/flows/suggestions/{txn_id}")
def flow_suggestions(txn_id: int, user=Depends(current_user), db=Depends(get_db)):
    t=db.execute("SELECT * FROM transactions WHERE id=? AND user_id=? AND status!='staged' AND removed_at IS NULL",(txn_id,user["id"])).fetchone()
    if not t:
        raise LookupError("Transaction not found")
    from datetime import timedelta
    start=(date.fromisoformat(t["date"])-timedelta(days=30)).isoformat()
    end=(date.fromisoformat(t["date"])+timedelta(days=30)).isoformat()
    rows=db.execute("SELECT t.id,t.date,t.amount_minor,t.direction,t.merchant,t.description,a.name AS account_name FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE t.user_id=? AND t.id!=? AND t.date BETWEEN ? AND ? AND t.direction!=? AND t.status!='staged' AND t.removed_at IS NULL AND NOT EXISTS(SELECT 1 FROM flow_group_members m WHERE m.txn_id=t.id) ORDER BY ABS(julianday(t.date)-julianday(?)), ABS(t.amount_minor-?) LIMIT 25",(user["id"],txn_id,start,end,t["direction"],t["date"],t["amount_minor"])).fetchall()
    return [{"txn":dict(row),"same_amount":row["amount_minor"]==t["amount_minor"],"same_merchant":bool(t["merchant_key"] and merchant_key(row["merchant"])==t["merchant_key"])} for row in rows]

@app.post("/api/flows")
def create_flow(b: FlowIn, user=Depends(current_user), db=Depends(get_db)):
    if b.kind not in ("pass_through","loan","repayment","reimbursement","temporary_transfer"):
        raise ValueError("Unknown flow kind")
    ids=list(dict.fromkeys(b.transaction_ids))
    if not (2<=len(ids)<=50):
        raise ValueError("Link between 2 and 50 transactions")
    marks=",".join("?" * len(ids))
    rows=db.execute(f"SELECT * FROM transactions WHERE user_id=? AND id IN ({marks}) AND status!='staged' AND removed_at IS NULL", [user["id"],*ids]).fetchall()
    if len(rows)!=len(ids) or db.execute(f"SELECT 1 FROM flow_group_members WHERE txn_id IN ({marks}) LIMIT 1",ids).fetchone() or db.execute(f"SELECT 1 FROM transaction_group_members WHERE txn_id IN ({marks}) LIMIT 1",ids).fetchone():
        raise ValueError("Some transactions cannot be linked; check existing flow groups")
    for row in rows:
        if row["dup_status"]=="suspected" or db.execute("SELECT 1 FROM splits WHERE txn_id=?", (row["id"],)).fetchone():
            raise ValueError("Resolve suspected duplicates and split categories before linking")
    cur=db.execute("INSERT INTO flow_groups(user_id,kind) VALUES(?,?)",(user["id"],b.kind))
    for row in rows:
        db.execute("INSERT INTO flow_group_members(txn_id,group_id,original_type,original_category_id,original_status,original_reviewed_at,original_skipped_at) VALUES(?,?,?,?,?,?,?)",(row["id"],cur.lastrowid,row["type"],row["category_id"],row["status"],row["reviewed_at"],row["skipped_at"]))
        db.execute("UPDATE transactions SET type='transfer',category_id=NULL,status='categorized',reviewed_at=datetime('now') WHERE id=?",(row["id"],))
    db.commit()
    return {"id":cur.lastrowid,"linked":len(rows)}

@app.get("/api/flows")
def list_flows(user=Depends(current_user), db=Depends(get_db)):
    groups=db.execute("SELECT * FROM flow_groups WHERE user_id=? ORDER BY id DESC",(user["id"],)).fetchall()
    return [{"id":g["id"],"kind":g["kind"],"transactions":[dict(r) for r in db.execute("SELECT t.id,t.date,t.direction,t.amount_minor,t.merchant FROM transactions t JOIN flow_group_members m ON m.txn_id=t.id WHERE m.group_id=? ORDER BY t.date,t.id",(g["id"],))]} for g in groups]

@app.delete("/api/flows/{group_id}")
def unlink_flow(group_id: int, user=Depends(current_user), db=Depends(get_db)):
    if not db.execute("SELECT 1 FROM flow_groups WHERE id=? AND user_id=?",(group_id,user["id"])).fetchone():
        raise LookupError("Flow not found")
    rows=db.execute("SELECT m.* FROM flow_group_members m JOIN transactions t ON t.id=m.txn_id WHERE m.group_id=? AND t.user_id=?",(group_id,user["id"])).fetchall()
    for row in rows:
        db.execute("UPDATE transactions SET type=?,category_id=?,status=?,reviewed_at=?,skipped_at=? WHERE id=?",(row["original_type"],row["original_category_id"],row["original_status"],row["original_reviewed_at"],row["original_skipped_at"],row["txn_id"]))
    db.execute("DELETE FROM flow_group_members WHERE group_id=?",(group_id,))
    db.execute("DELETE FROM flow_groups WHERE id=? AND user_id=?",(group_id,user["id"]))
    db.commit()
    return {"ok":True}

# ================================================================ static frontend

app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
