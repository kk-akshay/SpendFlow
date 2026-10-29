"""SQLite schema and connection helpers. Money is stored as integer minor units (paise/cents)."""
import os
import sqlite3

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  pw_hash BLOB NOT NULL,
  pw_salt BLOB NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions(
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS password_reset_tokens(
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_password_reset_user ON password_reset_tokens(user_id);

CREATE TABLE IF NOT EXISTS accounts(
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  type TEXT NOT NULL DEFAULT 'bank',
  last4 TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS categories(
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  color TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'expense',      -- expense | income | savings | transfer
  builtin INTEGER NOT NULL DEFAULT 0,
  sort INTEGER NOT NULL DEFAULT 0,
  UNIQUE(user_id, name)
);

CREATE TABLE IF NOT EXISTS statements(
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  mime TEXT,
  source_type TEXT,                           -- bank | gpay
  parser TEXT,                                -- columns | text | gpay | ai
  status TEXT NOT NULL DEFAULT 'preview',     -- preview | imported
  warnings TEXT NOT NULL DEFAULT '[]',
  date_from TEXT,
  date_to TEXT,
  txn_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transactions(
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  statement_id INTEGER REFERENCES statements(id) ON DELETE SET NULL,
  date TEXT NOT NULL,
  time TEXT,
  amount_minor INTEGER NOT NULL CHECK(amount_minor >= 0),
  direction TEXT NOT NULL CHECK(direction IN ('debit','credit')),
  type TEXT NOT NULL CHECK(type IN ('income','expense','transfer')),
  merchant TEXT NOT NULL DEFAULT '',
  merchant_key TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  ref TEXT,
  balance_minor INTEGER,
  category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
  note TEXT,
  recurring INTEGER NOT NULL DEFAULT 0,
  recurring_freq TEXT,
  status TEXT NOT NULL DEFAULT 'staged' CHECK(status IN ('staged','pending','categorized','skipped')),
  dup_status TEXT,                            -- NULL | exact | suspected | cleared
  dup_of INTEGER,
  transfer_pair_id INTEGER,
  flags TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  reviewed_at TEXT,
  skipped_at TEXT,
  removed_at TEXT,
  excluded_rule_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_txn_user_date ON transactions(user_id, date);
CREATE INDEX IF NOT EXISTS idx_txn_user_status ON transactions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_txn_user_amount ON transactions(user_id, amount_minor);
CREATE INDEX IF NOT EXISTS idx_txn_user_merchant ON transactions(user_id, merchant_key);
CREATE INDEX IF NOT EXISTS idx_txn_statement ON transactions(statement_id);

CREATE TABLE IF NOT EXISTS splits(
  id INTEGER PRIMARY KEY,
  txn_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
  category_id INTEGER NOT NULL REFERENCES categories(id),
  amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
  note TEXT
);
CREATE INDEX IF NOT EXISTS idx_splits_txn ON splits(txn_id);

CREATE TABLE IF NOT EXISTS merchant_rules(
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  merchant_key TEXT NOT NULL,
  category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  hits INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY(user_id, merchant_key)
);


CREATE TABLE IF NOT EXISTS import_exclusions(
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  merchant_key TEXT NOT NULL,
  description_key TEXT NOT NULL,
  amount_minor INTEGER NOT NULL,
  direction TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(user_id, account_id, merchant_key, description_key, amount_minor, direction)
);
CREATE TABLE IF NOT EXISTS classification_rules(
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  merchant_key TEXT NOT NULL,
  direction TEXT NOT NULL,
  category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  type TEXT NOT NULL CHECK(type IN ('income','expense','transfer')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(user_id, account_id, merchant_key, direction)
);
CREATE TABLE IF NOT EXISTS transaction_groups(
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('loan','repayment','pass_through','transfer')),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS transaction_group_members(
  group_id INTEGER NOT NULL REFERENCES transaction_groups(id) ON DELETE CASCADE,
  txn_id INTEGER NOT NULL UNIQUE REFERENCES transactions(id) ON DELETE CASCADE,
  original_type TEXT NOT NULL,
  original_category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
  original_status TEXT NOT NULL,
  original_reviewed_at TEXT,
  PRIMARY KEY(group_id, txn_id)
);
CREATE INDEX IF NOT EXISTS idx_groups_user ON transaction_groups(user_id);

CREATE TABLE IF NOT EXISTS exclusion_rules(
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  merchant_key TEXT NOT NULL,
  direction TEXT NOT NULL CHECK(direction IN ('debit','credit')),
  amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(user_id, account_id, merchant_key, direction, amount_minor)
);

CREATE TABLE IF NOT EXISTS flow_groups(
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK(kind IN ('pass_through','loan','repayment','reimbursement','temporary_transfer')),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS flow_group_members(
  txn_id INTEGER PRIMARY KEY REFERENCES transactions(id) ON DELETE CASCADE,
  group_id INTEGER NOT NULL REFERENCES flow_groups(id) ON DELETE CASCADE,
  original_type TEXT NOT NULL,
  original_category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
  original_status TEXT NOT NULL,
  original_reviewed_at TEXT,
  original_skipped_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_flow_group_members_group ON flow_group_members(group_id);

-- Separate people/contact ledgers from real bank accounts.
CREATE TABLE IF NOT EXISTS people(
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL CHECK(length(trim(name))>0),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_people_user ON people(user_id);
CREATE TABLE IF NOT EXISTS people_upi(
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
  upi_id TEXT NOT NULL,
  UNIQUE(user_id,upi_id)
);
CREATE INDEX IF NOT EXISTS idx_people_upi_person ON people_upi(person_id);
CREATE TABLE IF NOT EXISTS people_transactions(
  txn_id INTEGER PRIMARY KEY REFERENCES transactions(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  person_id INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK(role IN ('lent','repaid','borrowed','paid_back','other')),
  original_type TEXT NOT NULL,
  original_category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
  original_status TEXT NOT NULL,
  original_reviewed_at TEXT,
  original_skipped_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_people_transactions_person ON people_transactions(person_id);

CREATE TABLE IF NOT EXISTS budgets(
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  category_id INTEGER REFERENCES categories(id) ON DELETE CASCADE,   -- NULL = overall monthly limit
  limit_minor INTEGER NOT NULL CHECK(limit_minor > 0)
);

CREATE TABLE IF NOT EXISTS goals(
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  target_minor INTEGER NOT NULL CHECK(target_minor > 0),
  saved_minor INTEGER NOT NULL DEFAULT 0,
  deadline TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# name, colour, kind. Colours are mid-tone so they read on both light and dark surfaces.
DEFAULT_CATEGORIES = [
    ("Food", "#E07B39", "expense"),
    ("Groceries", "#5FA55A", "expense"),
    ("Transport", "#4A8FE0", "expense"),
    ("Shopping", "#C25BA8", "expense"),
    ("Bills", "#8B78D6", "expense"),
    ("Rent", "#B07D52", "expense"),
    ("Health", "#D9534F", "expense"),
    ("Entertainment", "#D8A82B", "expense"),
    ("Education", "#2FA39E", "expense"),
    ("Travel", "#3BAED6", "expense"),
    ("Family", "#E0809A", "expense"),
    ("Subscriptions", "#6E83E6", "expense"),
    ("Income", "#3DAA73", "income"),
    ("Savings", "#1F9D8B", "savings"),
    ("Transfers", "#8E98A4", "transfer"),
    ("Other", "#A09A92", "expense"),
]


def connect() -> sqlite3.Connection:
    if os.environ.get('DATABASE_URL'):
        raise RuntimeError('Use get_db() to obtain a PostgreSQL connection')
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db() -> None:
    if os.environ.get('DATABASE_URL'):
        from .postgres import init_postgres
        init_postgres(SCHEMA)
        return
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        # Additive migration for existing Tally databases; never rebuild financial rows.
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(transactions)")}
        if "removed_at" not in columns:
            conn.execute("ALTER TABLE transactions ADD COLUMN removed_at TEXT")
        if "excluded_rule_id" not in columns:
            conn.execute("ALTER TABLE transactions ADD COLUMN excluded_rule_id INTEGER")
        conn.commit()
    finally:
        conn.close()


def get_db():
    """FastAPI dependency: one connection per request."""
    if os.environ.get("DATABASE_URL"):
        from .postgres import PgConnection, pool
        with pool().connection() as connection:
            yield PgConnection(connection)
        return
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def seed_categories(db, user_id: int) -> None:
    for i, (name, color, kind) in enumerate(DEFAULT_CATEGORIES):
        db.execute(
            "INSERT OR IGNORE INTO categories(user_id,name,color,kind,builtin,sort) VALUES(?,?,?,?,1,?)",
            (user_id, name, color, kind, i),
        )
