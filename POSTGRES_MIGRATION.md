# PostgreSQL + Render deployment (migration branch)

This branch introduces an **optional** PostgreSQL database backend. The existing
SQLite configuration remains the default for local development and recovery.

## Important safety rules

- Never upload `tally.db`, `spendflow.db`, bank statements or real credentials to GitHub.
- This is a migration candidate, **not a production-ready deployment** until
  database integration and reconciliation tests have passed on a disposable
  PostgreSQL instance.
- Do not switch the existing Render service or delete the SQLite source yet.
- The original SQLite backup must remain available for rollback.
- PostgreSQL persists transactions, but not local statement files.

## Free hosting configuration

Create an **independent** Neon PostgreSQL database for SpendFlow. Its data must
not be shared with PlaceMate. Set these Render environment variables:

```text
DATABASE_URL=postgresql://...    # obtain from Neon; do not commit
SPENDFLOW_COOKIE_SECURE=1
SPENDFLOW_S3_ENDPOINT=https://... # endpoint from S3-compatible provider
SPENDFLOW_S3_BUCKET=...          # private bucket
SPENDFLOW_S3_ACCESS_KEY=...      # server-side secrets only
SPENDFLOW_S3_SECRET_KEY=...
SPENDFLOW_S3_REGION=auto         # provider-specific
```

The storage provider must actually support the S3 API. Verify its endpoint,
permissions, encryption, private access and pricing rather than assuming that
an object-storage product is enabled on a Neon account.

Render service settings:

- Repository: `kk-akshay/SpendFlow`
- Branch: migration branch for staging; only deploy master after tests/approval
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`

For scanned statements, use a deployment image with the `tesseract-ocr`
binary installed. Otherwise digital PDFs work, but OCR imports may fail.

## Local preflight and database migration

1. Stop the current local SpendFlow server.
2. Take a **consistent SQLite backup** (SQLite backup API is safer than copying
   a database file while its WAL is active). Back up `data/uploads/` separately.
3. Create a new, empty Neon database and place its URL in your local terminal's
   `DATABASE_URL` variable. Never paste that URL into issue comments or chats.
4. Run the preview:

   ```bash
   python -m backend.migrate_sqlite --source data/tally.db
   ```

   If your source is named `spendflow.db`, adjust the path.
5. Run `--apply` only against an **empty** disposable database, after backup:

   ```bash
   python -m backend.migrate_sqlite --source data/tally.db --apply
   ```

6. Validate users, transactions, categories, accounts, groups, balances,
   session behavior, and the end-to-end imports against PostgreSQL. The migration
   rejects populated tables and verifies counts and selected financial totals.
7. Existing stored file paths still reference original local files. Transfer
   these files separately to private object storage and update their paths
   **before switching production**; otherwise original statement downloads
   would no longer work. No automatic local-file migration is yet included.
8. Switch Render only after an approved staging test and clear rollback plan.

## Storage behavior

- When `SPENDFLOW_S3_BUCKET` is set, new imports upload documents to the private
  bucket and keep only temporary parser files on Render.
- If it is not set, files remain local, which is **not persistent on Render Free**.
- Normal financial pages read PostgreSQL and do not download original PDFs.
- Downloads are authenticated and the backend streams objects rather than
  returning public URLs.

## Known work still required before production cutover

- Run full PostgreSQL integration tests (including date and SQL-compatibility cases).
- Test migration on a copy of real SQLite data, not the only source.
- Migrate pre-existing local uploaded statement files.
- Validate Neon/Render quotas and actual storage provider credentials.
- Capture baseline and warm-instance latency benchmarks.
- Check Render cold-start behavior, backup/restore, and data recovery paths.
