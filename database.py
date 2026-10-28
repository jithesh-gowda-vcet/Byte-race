import sqlite3
from pathlib import Path
from datetime import datetime

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  normalized_name TEXT NOT NULL UNIQUE,
  quantity INTEGER NOT NULL DEFAULT 0 CHECK(quantity >= 0),
  unit TEXT NOT NULL DEFAULT 'units',
  min_stock INTEGER NOT NULL DEFAULT 5 CHECK(min_stock >= 0),
  selling_price_paise INTEGER NOT NULL DEFAULT 0 CHECK(selling_price_paise >= 0),
  cost_price_paise INTEGER NOT NULL DEFAULT 0 CHECK(cost_price_paise >= 0),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  normalized_name TEXT NOT NULL UNIQUE,
  phone TEXT,
  outstanding_balance_paise INTEGER NOT NULL DEFAULT 0 CHECK(outstanding_balance_paise >= 0),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inventory_transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER NOT NULL REFERENCES products(id),
  action TEXT NOT NULL,
  quantity INTEGER NOT NULL CHECK(quantity > 0),
  quantity_delta INTEGER NOT NULL,
  quantity_before INTEGER NOT NULL CHECK(quantity_before >= 0),
  quantity_after INTEGER NOT NULL CHECK(quantity_after >= 0),
  customer_id INTEGER REFERENCES customers(id),
  description TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS credit_transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id INTEGER NOT NULL REFERENCES customers(id),
  type TEXT NOT NULL CHECK(type IN ('credit_purchase','payment')),
  amount_paise INTEGER NOT NULL CHECK(amount_paise > 0),
  description TEXT NOT NULL DEFAULT '',
  inventory_transaction_id INTEGER REFERENCES inventory_transactions(id),
  balance_before_paise INTEGER NOT NULL CHECK(balance_before_paise >= 0),
  balance_after_paise INTEGER NOT NULL CHECK(balance_after_paise >= 0),
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  message_text TEXT NOT NULL,
  parsed_intent TEXT,
  status TEXT NOT NULL,
  response_text TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inventory_created ON inventory_transactions(created_at);
CREATE INDEX IF NOT EXISTS idx_inventory_product ON inventory_transactions(product_id);
CREATE INDEX IF NOT EXISTS idx_credit_customer ON credit_transactions(customer_id, created_at);
"""

SEED_PRODUCTS = [
    ("Maggi", "packets", 40, 10, 1500, 1200),
    ("Milk", "litres", 12, 5, 2800, 2400),
    ("Rice", "kg", 80, 15, 6500, 5400),
    ("Cooking oil", "litres", 8, 10, 14500, 12500),
    ("Sugar", "kg", 25, 5, 4500, 3800),
    ("Biscuits", "packets", 30, 8, 1000, 750),
]

SEED_CUSTOMERS = [("Ramesh", None), ("Suma", None), ("Kiran", None)]

def connect_db(path):
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn

def init_db(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect_db(path)
    try:
        conn.executescript(SCHEMA)
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        for name, unit, qty, minimum, selling, cost in SEED_PRODUCTS:
            conn.execute(
                """INSERT OR IGNORE INTO products
                (name, normalized_name, quantity, unit, min_stock, selling_price_paise,
                 cost_price_paise, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, name.casefold(), qty, unit, minimum, selling, cost, now, now),
            )
        for name, phone in SEED_CUSTOMERS:
            conn.execute(
                """INSERT OR IGNORE INTO customers
                (name, normalized_name, phone, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)""",
                (name, name.casefold(), phone, now, now),
            )
        conn.commit()
    finally:
        conn.close()

def get_db(path):
    return connect_db(path)
