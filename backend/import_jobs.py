"""Bounded asynchronous import runner: no DB connection held during PDF extraction.

Jobs use persistent DB status. Work is intentionally single-process; after a process
restart unfinished jobs are marked failed and can be retried by re-uploading.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import importing, parse_llm, storage
from .config import MAX_UPLOAD_BYTES, UPLOAD_DIR
from .db import get_db
from .extract import PasswordRequired, UnreadableDocument, sniff_kind
from .statement_parser import parse_file

log = logging.getLogger(__name__)
_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="spendflow-import")
_lock = threading.Lock()


def _db():
    return get_db()


def _set(job_id: str, status: str, result=None):
    from datetime import datetime, timezone
    dep = _db()
    db = next(dep)
    try:
        db.execute("UPDATE import_jobs SET status=?,result=?,updated_at=? WHERE id=?",
                   (status, json.dumps(result or {}), datetime.now(timezone.utc).isoformat(), job_id))
        db.commit()
    finally:
        try:
            next(dep)
        except StopIteration:
            pass


def enqueue(uid, files, account_id=None, new_name=None, new_type="bank", password=None, use_ai=False):
    """Save validated upload bytes quickly; submit CPU-heavy work outside HTTP request."""
    from datetime import datetime, timezone
    job_id = uuid.uuid4().hex
    user_dir = UPLOAD_DIR / str(uid) / "jobs" / job_id
    user_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, data in files:
        kind = sniff_kind(data[:16])
        if not kind or len(data) > MAX_UPLOAD_BYTES:
            manifest.append({"filename": name, "error": "Unsupported format or file too large."})
            continue
        path = user_dir / (uuid.uuid4().hex + {"pdf": ".pdf", "png": ".png", "jpeg": ".jpg", "webp": ".webp"}[kind])
        path.write_bytes(data)
        manifest.append({"filename": name, "path": str(path), "kind": kind,
                         "sha256": hashlib.sha256(data).hexdigest()})
    payload = {"files": manifest, "account_id": account_id, "new_name": new_name,
               "new_type": new_type, "use_ai": use_ai}
    dep = _db()
    db = next(dep)
    try:
        db.execute("INSERT INTO import_jobs(id,user_id,status,payload,result,updated_at) VALUES(?,?,?,?,?,?)",
                   (job_id, uid, "queued", json.dumps(payload), "{}", datetime.now(timezone.utc).isoformat()))
        db.commit()
    finally:
        try:
            next(dep)
        except StopIteration:
            pass
    _pool.submit(_process, job_id, uid, payload, password)
    return job_id


def _process(job_id, uid, payload, password):
    from .main import MIME, _resolve_account
    _set(job_id, "processing")
    results = []
    cache = {}
    try:
        for item in payload["files"]:
            name = item["filename"]
            result = {"filename": name, "ok": False}
            results.append(result)
            if "error" in item:
                result["error"] = item["error"]
                continue
            path = Path(item["path"])
            try:
                # Parsing occurs WITHOUT an open DB connection.
                parsed = parse_file(str(path), item["kind"], password, payload["use_ai"])
            except PasswordRequired:
                result.update(needs_password=True, error="Password required or incorrect.")
                continue
            except Exception:
                log.exception("Import parsing failed for job %s", job_id)
                result["error"] = "Unable to read statement."
                continue
            if not parsed.rows:
                result["error"] = "No usable transactions found."
                result["warnings"] = parsed.warnings
                continue
            dep = _db()
            db = next(dep)
            stored_path = None
            try:
                dup = db.execute("SELECT id,status FROM statements WHERE user_id=? AND sha256=?",
                                 (uid, item["sha256"])).fetchone()
                if dup:
                    result.update(error="This file has already been imported or uploaded.",
                                  statement_id=dup["id"])
                    continue
                aid = _resolve_account(db, uid, payload["account_id"], payload["new_name"],
                                       payload["new_type"], parsed, cache)
                stored_path = storage.persist(path, uid)
                sid = importing.create_statement(db, uid, aid, name, stored_path, item["sha256"],
                                                 MIME[item["kind"]], parsed)
                db.commit()
                result.update(ok=True, statement_id=sid, count=len(parsed.rows),
                              warnings=parsed.warnings, source_type=parsed.source_type)
            except Exception:
                db.rollback()
                log.exception("Import persistence failed for job %s", job_id)
                result["error"] = "Unable to securely save statement."
                if stored_path and stored_path.startswith("s3://"):
                    try:
                        storage.delete_file(stored_path, uid)
                    except Exception:
                        log.exception("Could not remove failed import object")
            finally:
                try:
                    next(dep)
                except StopIteration:
                    pass
        _set(job_id, "done", {"results": results})
    except Exception:
        log.exception("Background import job failed: %s", job_id)
        _set(job_id, "failed", {"detail": "Import failed. Please retry."})
    finally:
        import shutil
        for x in payload["files"]:
            if x.get("path"):
                Path(x["path"]).unlink(missing_ok=True)
        if payload["files"]:
            p = Path(next((x["path"] for x in payload["files"] if x.get("path")), ""))
            if p.name:
                shutil.rmtree(p.parent, ignore_errors=True)


def recover_interrupted_jobs():
    """No in-process worker survives a Render restart."""
    dep = _db()
    db = next(dep)
    try:
        db.execute("UPDATE import_jobs SET status='failed',result=? WHERE status IN ('queued','processing')",
                   ('{"detail":"Server restarted during import. Please upload the file again."}',))
        db.commit()
    finally:
        try:
            next(dep)
        except StopIteration:
            pass
