"""Copy historical statement files to private object storage after SQL migration.

Run on the machine containing the original SQLite uploads directory, with
DATABASE_URL and SPENDFLOW_S3_* variables configured. Idempotent: statements
already pointing at s3:// are ignored. This never removes local originals.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path

from . import storage
from .postgres import pool


def main(source_dir: Path, apply: bool):
    if not storage.cloud_enabled():
        raise SystemExit("Configure a private SPENDFLOW_S3_BUCKET and credentials first")
    if not os.getenv("DATABASE_URL"):
        raise SystemExit("Configure DATABASE_URL first")
    with pool().connection() as db:
        rows = db.execute("SELECT id,user_id,stored_path,sha256 FROM statements ORDER BY id").fetchall()
        missing, done, pending = [], 0, 0
        for st in rows:
            if st["stored_path"].startswith("s3://"):
                done += 1
                continue
            candidate = Path(st["stored_path"])
            if not candidate.is_file():
                candidate = source_dir / str(st["user_id"]) / Path(st["stored_path"].replace("\\\\", "/")).name
            if not candidate.is_file():
                missing.append(st["id"])
                continue
            actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
            if actual != st["sha256"]:
                raise RuntimeError(f"SHA-256 mismatch for statement {st['id']}; refusing upload")
            pending += 1
            if not apply:
                continue
            uri = storage.persist(candidate, st["user_id"])
            try:
                result = db.execute(
                    "UPDATE statements SET stored_path=%s WHERE id=%s AND stored_path=%s",
                    (uri, st["id"], st["stored_path"]))
                if result.rowcount != 1:
                    raise RuntimeError("Concurrent update detected for statement " + str(st["id"]))
                db.commit()
            except Exception:
                db.rollback()
                storage.delete_file(uri, st["user_id"])
                raise
            print(f"Uploaded and updated statement {st['id']}")
        print(f"Already cloud-backed: {done}; found local files: {pending}; missing source files: {len(missing)}")
        if missing:
            print("Missing statement IDs:", ", ".join(map(str, missing)))
            if apply:
                raise SystemExit("Some historical files could not be found. Database links remain unchanged.")
        if not apply:
            print("DRY RUN. No files uploaded. Add --apply after verifying counts.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-uploads", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    main(args.source_uploads, args.apply)
