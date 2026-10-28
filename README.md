# DukaanMitra — Kirana Chat Ledger

A beginner-friendly full-stack MVP for small Indian grocery shops. The app uses Flask, SQLite, HTML, CSS, and vanilla JavaScript. Chat understanding uses deterministic Python rules and regular expressions; no paid AI API is required.

## Features

- Real dashboard metrics calculated from the SQLite database.
- Chat commands for sales, stock received, damaged goods, customer returns, customer credit purchases, payments, low stock, daily summary, customer balances, and supplier reorder text.
- Atomic multi-item inventory updates: all products and quantities are validated before any stock changes are committed.
- Inventory search, add/edit product, and manual stock adjustment with a reason.
- Customer ledger, credit purchases, payment entries, and transaction history.
- Daily report for a selected date and editable/copyable supplier reorder message.
- SQLite persistence, foreign keys, parameterized SQL, backend validation, and automated tests.

## Requirements

- Python 3.10 or newer
- pip

## Run locally

From the project directory:

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

If PowerShell blocks activation, use Command Prompt:

```bat
py -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000.

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

The SQLite database is stored in Flask's instance directory (`instance/dukaanmitra.sqlite3`) by default. To choose a different persistent database path, set `DUKAANMITRA_DATABASE` before starting the app.

## Run tests

```bash
python -m unittest discover -s tests -v
```

Tests use temporary isolated databases and do not modify the demo database.

## Example chat commands

- `sold 3 Maggi`
- `sold 3 Maggi, 2 milk`
- `received 20 rice`
- `damaged 1 cooking oil`
- `returned 2 milk`
- `Ramesh took 2 rice on credit`
- `Ramesh paid 200`
- `show low stock`
- `show today's summary`
- `what does Ramesh owe?`
- `generate supplier reorder message`

Use the full product name when matching might be ambiguous. Product matching is case-insensitive. Customer names must be unique; a credit command requires the customer to exist. The credit purchase uses each product's configured selling price and atomically reduces stock while increasing the customer's balance. Payments cannot exceed the current balance and do not affect inventory.

## Architecture

```text
Browser (HTML/CSS/vanilla JS)
        │ Fetch JSON
        ▼
Flask routes (app.py)
        │
        ▼
Service layer (services.py)
  - parse and validate commands
  - business rules
  - atomic SQLite transactions
        │
        ▼
SQLite database (instance/dukaanmitra.sqlite3)
```

- `app.py`: routes, request parsing, HTTP error handling.
- `database.py`: schema, SQLite connections, safe demo-data initialization.
- `services.py`: deterministic parser and all inventory/customer/report business logic.
- `templates/index.html`: responsive dashboard and page structure.
- `static/styles.css`: styling and responsive layouts.
- `static/app.js`: browser navigation, API calls, chat, tables, and forms.
- `tests/test_services.py`: critical business logic tests.

## API route summary

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/health` | Health check |
| GET | `/api/dashboard` | Dashboard metrics and recent stock movements |
| GET | `/api/products` | Search/list products; optional `low_stock=1` |
| POST | `/api/products` | Create product |
| PATCH | `/api/products/<id>` | Edit product details |
| POST | `/api/products/<id>/adjust` | Manual stock adjustment |
| GET | `/api/transactions` | Recent inventory transactions |
| POST | `/api/chat` | Parse and process a chat command |
| GET | `/api/customers` | Search/list customers |
| POST | `/api/customers` | Create customer |
| GET | `/api/customers/<id>/transactions` | Customer credit history |
| POST | `/api/credit` | Record a payment or manual credit adjustment |
| GET | `/api/reports/daily?date=YYYY-MM-DD` | Daily report |
| GET | `/api/low-stock` | Current low-stock products |
| GET | `/api/supplier-message` | Generate reorder text from current low stock |

JSON errors have an `error` field and an appropriate HTTP status. Chat validation errors return HTTP 422 and do not change stock. Other invalid form/API data returns HTTP 400.

## Six-hour hackathon demo plan

1. **0:00–0:30 — Launch and explain**: show the app, health endpoint, database, and seeded demo products.
2. **0:30–1:30 — Main story**: run `sold 3 Maggi, 2 milk`; show actual before/after quantities and dashboard refresh.
3. **1:30–2:15 — Integrity proof**: attempt a sale larger than available stock and show it is rejected without partial changes.
4. **2:15–3:15 — Stock management**: receive rice, record damaged oil, record returned milk, add a product, and adjust stock with a reason.
5. **3:15–4:15 — Udhaar**: record `Ramesh took 2 rice on credit`; then record a payment and show stock is unchanged by the payment.
6. **4:15–5:00 — Reporting**: show low stock, the daily report, and supplier reorder message.
7. **5:00–5:40 — QA**: run the automated tests and fix any environment-specific issues.
8. **5:40–6:00 — Final demo rehearsal**: reset only the demo database if desired, agree on speaking roles, and rehearse the same commands.

## Known limitations

- This is a local single-shop demo, not a hardened multi-shop production system. There is no login/authentication, role-based access control, CSRF protection, or tenant isolation.
- The demo database is local to the machine. Backups, deployment, concurrent multi-user operations, and production monitoring are not configured.
- The command parser intentionally supports a documented set of simple command formats. It is not a general natural-language model. Unsupported or ambiguous messages should be rephrased.
- A credit purchase computes its amount from configured selling prices. Set prices before using the credit-purchase command.
- Supplier reorder quantities are a simple heuristic (`2 × minimum stock − current stock`, with a minimum of one unit), not an optimized demand forecast.
- The dashboard uses a sample shop name and demo seed products/customers. Seed data is inserted only when a product/customer name is not already present.
- Currency is stored as integer paise; quantities are whole numbers. Fractional quantities (e.g. 0.5 kg) are not supported in this MVP.
- The UI loads Google Fonts from a CDN if internet is available; the core functionality works without it.

## Safety and data integrity notes

- All SQL uses parameterized values.
- SQLite foreign keys are enabled for every connection.
- Stock movements and linked credit purchases are wrapped in database transactions.
- Multi-item commands validate all products and stock levels before changing any quantities.
- No stock is allowed to go negative.
- Chat responses confirm changes only after the database commit succeeds.
