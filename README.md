# Tally

A personal finance app that helps you understand where your money goes. Upload bank or Google Pay statements
(PDF or image), then answer "What was this transaction for?" one card at a time.

## Run it

```bash
sudo apt install tesseract-ocr          # needed for scanned PDFs and images
pip install -r requirements.txt
python3 -m uvicorn backend.main:app --port 8000
# open http://localhost:8000 and create an account
```

Data lives in `data/` (SQLite database + uploaded files). Override with `TALLY_DATA=/path`.
Optional: `TALLY_CURRENCY=INR|USD|...`, `TALLY_COOKIE_SECURE=1` when served over HTTPS,
`ANTHROPIC_API_KEY=...` to enable the opt-in "Use AI to read it" checkbox on import.

## How it works

- **Import**: `extract.py` reads text with pdfplumber, or OCRs scans/images with Tesseract. `parse_bank.py` finds
  the Debit/Credit/Balance columns by position and checks every row against the running balance; `parse_gpay.py`
  reads Google Pay blocks. Imports land in a **preview** you confirm before anything is counted.
- **Review**: one card at a time, ordered by date. Every answer is saved immediately; reload or come back later
  and it resumes at the next unreviewed transaction. Keys: `Enter` accept suggestion, `1-0 q-y` categories,
  `Space`/`←` skip, `→` accept, `Backspace` undo, `n` note, `/` split, `.` recurring, `+` new category.
  On mobile, swipe right to accept the suggestion and left to skip.
- **Suggestions**: your own history first, then fuzzy matches of past merchants, then built-in keywords.
- **Duplicates**: exact re-imports are skipped; the same payment seen in two sources (bank + Google Pay) is
  held out of totals until you choose. **Transfers** between your accounts are matched (same amount, opposite
  direction, within 3 days) and never counted as income or spending.
- **Privacy**: per-user data, httpOnly session cookie, CSRF header, content-sniffed uploads. You can delete a
  statement (with or without its transactions), wipe all data, or delete the account.

## Tests

```bash
python3 tests/make_samples.py tests/samples   # synthetic statements with ground truth
python3 tests/check_parsers.py tests/samples  # parser accuracy
python3 tests/api_test.py tests/samples       # 57 end-to-end API checks
```

## Known limits

- Parsers were tested on synthetic statements in three bank layouts plus Google Pay, not on real statements
  from every bank. Digital PDFs parsed exactly; **OCR from low-quality images is much weaker** (about 30-40%
  of rows exact on a deliberately degraded scan, 100% on a clean screenshot). Rows that fail the balance check
  or look odd are flagged in the preview, and you can edit, delete or add rows before confirming.
  For scans, prefer the original PDF, or enable the AI option.
- Google Pay statement layouts change; the reader expects the "Paid to / Received from + UPI Transaction ID" format.
- Single-user-per-login, SQLite, one server process. No password reset by email.
