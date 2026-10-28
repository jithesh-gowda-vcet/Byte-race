import re
import sqlite3
from datetime import datetime, date, time
from decimal import Decimal, InvalidOperation
from database import get_db

class ValidationError(ValueError):
    pass

class NotFoundError(LookupError):
    pass

def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")

def normalize(value):
    return " ".join(str(value).strip().casefold().split())

def row_dict(row):
    return dict(row) if row is not None else None

def money_rupees(paise):
    return f"₹{paise / 100:,.2f}"

def parse_money_paise(value, allow_zero=False):
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError):
        raise ValidationError("Enter a valid rupee amount.")
    if not amount.is_finite() or amount < 0 or (amount == 0 and not allow_zero) or amount > Decimal("100000000"):
        raise ValidationError("Amount must be non-negative when allowed, otherwise greater than zero, and within the supported limit.")
    return int((amount * 100).quantize(Decimal("1")))

def _product_public(row):
    p = dict(row)
    p["selling_price"] = p["selling_price_paise"] / 100
    p["cost_price"] = p["cost_price_paise"] / 100
    p["stock_status"] = "low" if p["quantity"] <= p["min_stock"] else "healthy"
    return p

def list_products(db_path, q="", low_stock=False):
    conn = get_db(db_path)
    try:
        sql = "SELECT * FROM products"
        clauses, args = [], []
        if q:
            clauses.append("name LIKE ?")
            args.append(f"%{q}%")
        if low_stock:
            clauses.append("quantity <= min_stock")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY name COLLATE NOCASE"
        return [_product_public(r) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()

def create_product(db_path, data):
    name = str(data.get("name", "")).strip()
    unit = str(data.get("unit", "units")).strip()
    qty = _integer(data.get("quantity", 0), "Quantity", minimum=0, maximum=1_000_000)
    minimum = _integer(data.get("min_stock", 5), "Minimum stock", minimum=0, maximum=1_000_000)
    selling = parse_money_paise(data["selling_price"], allow_zero=True) if data.get("selling_price") not in (None, "") else 0
    cost = parse_money_paise(data["cost_price"], allow_zero=True) if data.get("cost_price") not in (None, "") else 0
    if not name or len(name) > 80:
        raise ValidationError("Product name is required and must be at most 80 characters.")
    if not unit or len(unit) > 24:
        raise ValidationError("Unit is required and must be at most 24 characters.")
    now = now_iso()
    conn = get_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute("""INSERT INTO products
            (name, normalized_name, quantity, unit, min_stock, selling_price_paise, cost_price_paise, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, normalize(name), qty, unit, minimum, selling, cost, now, now))
        if qty:
            conn.execute("""INSERT INTO inventory_transactions
                (product_id, action, quantity, quantity_delta, quantity_before, quantity_after, description, created_at)
                VALUES (?, 'opening_stock', ?, ?, 0, ?, 'Opening stock', ?)""",
                (cur.lastrowid, qty, qty, qty, now))
        conn.commit()
        return _product_public(conn.execute("SELECT * FROM products WHERE id=?", (cur.lastrowid,)).fetchone())
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        if "normalized_name" in str(exc):
            raise ValidationError("A product with that name already exists.")
        raise ValidationError("Product could not be saved. Check the values.")
    finally:
        conn.close()

def update_product(db_path, product_id, data):
    allowed = {"name", "unit", "min_stock", "selling_price", "cost_price"}
    if not any(k in data for k in allowed):
        raise ValidationError("Provide at least one field to update.")
    conn = get_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        old = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        if not old:
            raise NotFoundError("Product not found.")
        name = str(data.get("name", old["name"])).strip()
        unit = str(data.get("unit", old["unit"])).strip()
        minimum = _integer(data.get("min_stock", old["min_stock"]), "Minimum stock", 0, 1_000_000)
        selling = parse_money_paise(data["selling_price"], allow_zero=True) if "selling_price" in data else old["selling_price_paise"]
        cost = parse_money_paise(data["cost_price"], allow_zero=True) if "cost_price" in data else old["cost_price_paise"]
        if not name or len(name) > 80 or not unit or len(unit) > 24:
            raise ValidationError("Product name or unit is invalid.")
        conn.execute("""UPDATE products SET name=?, normalized_name=?, unit=?, min_stock=?,
            selling_price_paise=?, cost_price_paise=?, updated_at=? WHERE id=?""",
            (name, normalize(name), unit, minimum, selling, cost, now_iso(), product_id))
        conn.commit()
        return _product_public(conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone())
    except sqlite3.IntegrityError:
        conn.rollback()
        raise ValidationError("A product with that name already exists.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def _integer(value, label, minimum=1, maximum=1_000_000):
    if isinstance(value, bool):
        raise ValidationError(f"{label} must be a whole number.")
    try:
        s = str(value).strip()
        if not re.fullmatch(r"\d+", s):
            raise ValueError()
        result = int(s)
    except (ValueError, TypeError):
        raise ValidationError(f"{label} must be a whole number.")
    if result < minimum or result > maximum:
        raise ValidationError(f"{label} must be between {minimum} and {maximum}.")
    return result

def _resolve_product(conn, name):
    norm = normalize(name)
    rows = conn.execute("SELECT * FROM products WHERE normalized_name=?", (norm,)).fetchall()
    if len(rows) == 1:
        return rows[0]
    # A single unique substring can be accepted, but multiple matches require clarification.
    rows = conn.execute("SELECT * FROM products WHERE normalized_name LIKE ?", (f"%{norm}%",)).fetchall()
    if len(rows) == 1:
        return rows[0]
    if len(rows) > 1:
        raise ValidationError(f"'{name}' matches multiple products. Use the full product name.")
    raise ValidationError(f"Unknown product '{name}'. Add it in Inventory first.")

def _resolve_customer(conn, name):
    norm = normalize(name)
    row = conn.execute("SELECT * FROM customers WHERE normalized_name=?", (norm,)).fetchone()
    if not row:
        raise ValidationError(f"Customer '{name}' was not found. Add the customer first.")
    return row

def _parse_items(text):
    # Items are comma-separated, e.g. "3 Maggi, 2 milk"; quantity must precede name.
    parts = [p.strip() for p in re.split(r"\s*,\s*|\s+\band\b\s+", text, flags=re.I) if p.strip()]
    if not parts:
        raise ValidationError("Include at least one item, for example: sold 3 Maggi.")
    items = []
    for part in parts:
        match = re.fullmatch(r"(\d+)\s+(.+?)(?:\s+(?:x|units?))?", part, flags=re.I)
        if not match:
            raise ValidationError(f"I couldn't read '{part}'. Use a quantity followed by a product name.")
        qty = _integer(match.group(1), "Quantity", 1, 1_000_000)
        name = match.group(2).strip()
        if not name:
            raise ValidationError("A product name is missing.")
        items.append((name, qty))
    return items

def _apply_inventory(conn, action, items, customer_id=None, description=""):
    # Resolve and validate every product and stock balance before writing any change.
    resolved = []
    for name, qty in items:
        p = _resolve_product(conn, name)
        resolved.append((p, qty))
    # Aggregate repeated product names to avoid stale quantity checks.
    totals = {}
    for p, qty in resolved:
        totals[p["id"]] = totals.get(p["id"], 0) + qty
    current = {pid: conn.execute("SELECT * FROM products WHERE id=?", (pid,)).fetchone() for pid in totals}
    outgoing = action in ("sold", "damaged", "credit_purchase", "manual_decrease")
    if outgoing:
        for pid, total in totals.items():
            if current[pid]["quantity"] < total:
                raise ValidationError(f"Not enough {current[pid]['name']} in stock. Available: {current[pid]['quantity']} {current[pid]['unit']}.")
    results = []
    for p, qty in resolved:
        before = conn.execute("SELECT quantity FROM products WHERE id=?", (p["id"],)).fetchone()["quantity"]
        delta = -qty if outgoing else qty
        after = before + delta
        conn.execute("UPDATE products SET quantity=?, updated_at=? WHERE id=?", (after, now_iso(), p["id"]))
        cur = conn.execute("""INSERT INTO inventory_transactions
            (product_id, action, quantity, quantity_delta, quantity_before, quantity_after, customer_id, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (p["id"], action, qty, delta, before, after, customer_id, description, now_iso()))
        results.append({"product": p["name"], "quantity": qty, "unit": p["unit"], "before": before, "after": after, "delta": delta, "transaction_id": cur.lastrowid})
    return results

def process_chat(db_path, message):
    msg = " ".join(message.strip().split())
    if len(msg) > 500:
        raise ValidationError("Message is too long (maximum 500 characters).")
    conn = get_db(db_path)
    intent = "unknown"
    try:
        conn.execute("BEGIN IMMEDIATE")
        lower = msg.casefold()
        if lower in ("show low stock", "low stock", "show low-stock", "low-stock"):
            intent = "low_stock"
            rows = conn.execute("SELECT name, quantity, unit, min_stock FROM products WHERE quantity <= min_stock ORDER BY quantity ASC").fetchall()
            answer = "No products are at or below their minimum stock threshold." if not rows else "Low-stock products:\n" + "\n".join(f"• {r['name']}: {r['quantity']} {r['unit']} (minimum {r['min_stock']})" for r in rows)
            result = {"ok": True, "intent": intent, "message": answer, "items": [dict(r) for r in rows]}
        elif lower in ("show today's summary", "show todays summary", "today summary", "daily summary", "show daily summary"):
            intent = "daily_summary"
            result = {"ok": True, "intent": intent, "message": _summary_text(conn), "summary": _daily_summary_conn(conn, date.today().isoformat())}
        elif re.fullmatch(r"what does .+ owe\??", msg, flags=re.I) or re.fullmatch(r".+ owes\??", msg, flags=re.I):
            intent = "customer_balance"
            match = re.fullmatch(r"what does (.+?) owe\??", msg, flags=re.I) or re.fullmatch(r"(.+?) owes\??", msg, flags=re.I)
            customer = _resolve_customer(conn, match.group(1))
            balance = customer["outstanding_balance_paise"]
            result = {"ok": True, "intent": intent, "message": f"{customer['name']} owes {money_rupees(balance)}.", "customer": customer["name"], "balance_paise": balance}
        elif lower.startswith("generate supplier reorder message") or lower in ("supplier message", "reorder message"):
            intent = "supplier_message"
            rows = conn.execute("SELECT name, quantity, unit, min_stock FROM products WHERE quantity <= min_stock ORDER BY name COLLATE NOCASE").fetchall()
            lines = [f"- {r['name']}: {max(r['min_stock'] * 2 - r['quantity'], 1)} {r['unit']}" for r in rows]
            message_text = "Hello, please send the following items:\n" + "\n".join(lines) + "\nThank you." if lines else "No items currently need reordering."
            result = {"ok": True, "intent": intent, "message": message_text, "supplier_message": message_text}
        elif re.match(r"^(r(?:amesh|amesh)?|.+?)\s+(?:paid|payment of)\s+.+$", msg, flags=re.I):
            # Deliberately only accepts a numeric rupee amount after "paid".
            m = re.fullmatch(r"(.+?)\s+paid\s+₹?\s*(\d+(?:\.\d{1,2})?)", msg, flags=re.I)
            if not m:
                raise ValidationError("Use this format to record a payment: Ramesh paid 200.")
            intent = "payment"
            customer = _resolve_customer(conn, m.group(1))
            amount = parse_money_paise(m.group(2))
            before = customer["outstanding_balance_paise"]
            if amount > before:
                raise ValidationError(f"Payment exceeds {customer['name']}'s outstanding balance of {money_rupees(before)}.")
            after = before - amount
            conn.execute("UPDATE customers SET outstanding_balance_paise=?, updated_at=? WHERE id=?", (after, now_iso(), customer["id"]))
            conn.execute("""INSERT INTO credit_transactions
                (customer_id, type, amount_paise, description, balance_before_paise, balance_after_paise, created_at)
                VALUES (?, 'payment', ?, ?, ?, ?, ?)""",
                (customer["id"], amount, "Payment recorded from chat", before, after, now_iso()))
            result = {"ok": True, "intent": intent, "message": f"Payment recorded: {customer['name']} paid {money_rupees(amount)}. Balance: {money_rupees(before)} → {money_rupees(after)}.", "customer": customer["name"], "amount_paise": amount, "balance_before_paise": before, "balance_after_paise": after}
        elif re.match(r"^.+?\s+took\s+.+?\s+on\s+credit$", msg, flags=re.I):
            m = re.fullmatch(r"(.+?)\s+took\s+(.+?)\s+on\s+credit", msg, flags=re.I)
            intent = "credit_purchase"
            customer = _resolve_customer(conn, m.group(1))
            items = _parse_items(m.group(2))
            # Price is based on the current selling price and all products are validated before changes.
            validated = []
            for name, qty in items:
                p = _resolve_product(conn, name)
                if p["selling_price_paise"] <= 0:
                    raise ValidationError(f"Set a selling price for {p['name']} before recording a credit purchase.")
                validated.append((p, qty))
            inventory_results = _apply_inventory(conn, "credit_purchase", items, customer["id"], "Customer credit purchase")
            amount = sum(_resolve_product(conn, name)["selling_price_paise"] * qty for name, qty in items)
            before = customer["outstanding_balance_paise"]
            after = before + amount
            conn.execute("UPDATE customers SET outstanding_balance_paise=?, updated_at=? WHERE id=?", (after, now_iso(), customer["id"]))
            inv_id = inventory_results[0]["transaction_id"] if inventory_results else None
            conn.execute("""INSERT INTO credit_transactions
                (customer_id, type, amount_paise, description, inventory_transaction_id, balance_before_paise, balance_after_paise, created_at)
                VALUES (?, 'credit_purchase', ?, ?, ?, ?, ?, ?)""",
                (customer["id"], amount, "Credit purchase from chat", inv_id, before, after, now_iso()))
            result = {"ok": True, "intent": intent, "message": f"Credit purchase recorded for {customer['name']}: {money_rupees(amount)} added to udhaar. New balance: {money_rupees(after)}.", "customer": customer["name"], "amount_paise": amount, "balance_before_paise": before, "balance_after_paise": after, "items": inventory_results}
        else:
            action_match = re.match(r"^(sold|received|damaged|returned)\s+(.+)$", msg, flags=re.I)
            if not action_match:
                raise ValidationError("I couldn't understand that. Try “sold 3 Maggi”, “Ramesh took 2 rice on credit”, or “show low stock”.")
            action = action_match.group(1).casefold()
            intent = action
            items = _parse_items(action_match.group(2))
            inventory_results = _apply_inventory(conn, action, items, description=f"Chat command: {msg}")
            labels = {"sold": "Sale recorded", "received": "Stock received", "damaged": "Damaged stock recorded", "returned": "Customer return recorded"}
            lines = [f"• {r['product']}: {r['before']} → {r['after']} {r['unit']}" for r in inventory_results]
            result = {"ok": True, "intent": intent, "message": labels[action] + ":\n" + "\n".join(lines), "items": inventory_results}
        conn.execute("INSERT INTO chat_messages (message_text, parsed_intent, status, response_text, created_at) VALUES (?, ?, ?, ?, ?)",
                     (msg, intent, "success", result["message"], now_iso()))
        conn.commit()
        return result
    except (ValidationError, NotFoundError) as exc:
        conn.rollback()
        try:
            conn.execute("INSERT INTO chat_messages (message_text, parsed_intent, status, response_text, created_at) VALUES (?, ?, 'error', ?, ?)",
                         (msg, intent, str(exc), now_iso()))
            conn.commit()
        except Exception:
            conn.rollback()
        return {"ok": False, "intent": intent, "error": str(exc), "message": str(exc)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def adjust_stock(db_path, product_id, data):
    direction = data.get("direction")
    qty = _integer(data.get("quantity"), "Quantity", 1, 1_000_000)
    reason = str(data.get("reason", "")).strip()
    if direction not in ("increase", "decrease"):
        raise ValidationError("Direction must be increase or decrease.")
    if not reason or len(reason) > 200:
        raise ValidationError("Enter a reason (maximum 200 characters).")
    conn = get_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        p = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        if not p:
            raise NotFoundError("Product not found.")
        before = p["quantity"]
        delta = qty if direction == "increase" else -qty
        after = before + delta
        if after < 0:
            raise ValidationError(f"Cannot reduce stock below zero. Available: {before} {p['unit']}.")
        conn.execute("UPDATE products SET quantity=?, updated_at=? WHERE id=?", (after, now_iso(), product_id))
        conn.execute("""INSERT INTO inventory_transactions
            (product_id, action, quantity, quantity_delta, quantity_before, quantity_after, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (product_id, "manual_adjustment", qty, delta, before, after, reason, now_iso()))
        conn.commit()
        return {"ok": True, "product": p["name"], "before": before, "after": after, "unit": p["unit"]}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def list_customers(db_path, q=""):
    conn = get_db(db_path)
    try:
        sql = """SELECT c.*, COUNT(t.id) AS transaction_count FROM customers c
                 LEFT JOIN credit_transactions t ON t.customer_id=c.id"""
        args = []
        if q:
            sql += " WHERE c.name LIKE ? OR COALESCE(c.phone, '') LIKE ?"
            args = [f"%{q}%", f"%{q}%"]
        sql += " GROUP BY c.id ORDER BY c.name COLLATE NOCASE"
        rows = conn.execute(sql, args).fetchall()
        return [{**dict(r), "outstanding_balance": r["outstanding_balance_paise"] / 100} for r in rows]
    finally:
        conn.close()

def create_customer(db_path, data):
    name = str(data.get("name", "")).strip()
    phone = str(data.get("phone", "")).strip() or None
    if not name or len(name) > 80:
        raise ValidationError("Customer name is required and must be at most 80 characters.")
    if phone and (len(phone) > 24 or not re.fullmatch(r"[+\d ()-]+", phone)):
        raise ValidationError("Enter a valid phone number or leave it blank.")
    conn = get_db(db_path)
    try:
        now = now_iso()
        cur = conn.execute("INSERT INTO customers (name, normalized_name, phone, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                           (name, normalize(name), phone, now, now))
        conn.commit()
        return dict(conn.execute("SELECT * FROM customers WHERE id=?", (cur.lastrowid,)).fetchone())
    except sqlite3.IntegrityError:
        conn.rollback()
        raise ValidationError("A customer with that name already exists. Use a unique name.")
    finally:
        conn.close()

def customer_transactions(db_path, customer_id):
    conn = get_db(db_path)
    try:
        if not conn.execute("SELECT id FROM customers WHERE id=?", (customer_id,)).fetchone():
            raise NotFoundError("Customer not found.")
        return [dict(r) for r in conn.execute("""SELECT * FROM credit_transactions WHERE customer_id=? ORDER BY created_at DESC, id DESC""", (customer_id,)).fetchall()]
    finally:
        conn.close()

def record_credit(db_path, data):
    kind = data.get("type")
    customer_id = _integer(data.get("customer_id"), "Customer", 1, 10_000_000)
    amount = parse_money_paise(data.get("amount"))
    description = str(data.get("description", "")).strip() or ("Payment" if kind == "payment" else "Credit adjustment")
    if len(description) > 200:
        raise ValidationError("Description must be at most 200 characters.")
    if kind not in ("payment", "credit_adjustment"):
        raise ValidationError("Type must be payment or credit_adjustment.")
    conn = get_db(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        customer = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        if not customer:
            raise NotFoundError("Customer not found.")
        before = customer["outstanding_balance_paise"]
        if kind == "payment":
            if amount > before:
                raise ValidationError(f"Payment exceeds outstanding balance of {money_rupees(before)}.")
            after = before - amount
            txn_type = "payment"
        else:
            after = before + amount
            txn_type = "credit_purchase"
        conn.execute("UPDATE customers SET outstanding_balance_paise=?, updated_at=? WHERE id=?", (after, now_iso(), customer_id))
        conn.execute("""INSERT INTO credit_transactions
            (customer_id, type, amount_paise, description, balance_before_paise, balance_after_paise, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (customer_id, txn_type, amount, description, before, after, now_iso()))
        conn.commit()
        return {"ok": True, "customer": customer["name"], "type": txn_type, "amount_paise": amount, "balance_before_paise": before, "balance_after_paise": after}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def low_stock_products(db_path):
    return list_products(db_path, low_stock=True)

def dashboard_data(db_path):
    conn = get_db(db_path)
    try:
        today = date.today().isoformat()
        product_count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        total_units = conn.execute("SELECT COALESCE(SUM(quantity),0) FROM products").fetchone()[0]
        low_count = conn.execute("SELECT COUNT(*) FROM products WHERE quantity <= min_stock").fetchone()[0]
        sales = conn.execute("SELECT COUNT(*) FROM inventory_transactions WHERE action='sold' AND substr(created_at,1,10)=?", (today,)).fetchone()[0]
        sales_qty = conn.execute("SELECT COALESCE(SUM(quantity),0) FROM inventory_transactions WHERE action='sold' AND substr(created_at,1,10)=?", (today,)).fetchone()[0]
        credit = conn.execute("SELECT COALESCE(SUM(outstanding_balance_paise),0) FROM customers").fetchone()[0]
        recent = conn.execute("""SELECT t.*, p.name AS product_name, p.unit FROM inventory_transactions t
            JOIN products p ON p.id=t.product_id ORDER BY t.id DESC LIMIT 8""").fetchall()
        return {"product_count": product_count, "total_units": total_units, "low_stock_count": low_count,
                "sales_transactions_today": sales, "units_sold_today": sales_qty,
                "outstanding_credit_paise": credit, "outstanding_credit": credit/100,
                "recent_transactions": [dict(r) for r in recent],
                "low_stock_products": low_stock_products(db_path)}
    finally:
        conn.close()

def _daily_summary_conn(conn, day):
    rows = conn.execute("""SELECT action, COALESCE(SUM(quantity),0) AS quantity, COUNT(*) AS transactions
        FROM inventory_transactions WHERE substr(created_at,1,10)=? GROUP BY action""", (day,)).fetchall()
    movement = {r["action"]: {"quantity": r["quantity"], "transactions": r["transactions"]} for r in rows}
    credits = conn.execute("""SELECT type, COALESCE(SUM(amount_paise),0) AS amount_paise, COUNT(*) AS transactions
        FROM credit_transactions WHERE substr(created_at,1,10)=? GROUP BY type""", (day,)).fetchall()
    credit_summary = {r["type"]: {"amount_paise": r["amount_paise"], "transactions": r["transactions"]} for r in credits}
    return {"date": day, "inventory_movements": movement, "credit": credit_summary}

def _summary_text(conn):
    data = _daily_summary_conn(conn, date.today().isoformat())
    m = data["inventory_movements"]
    sold = m.get("sold", {}).get("quantity", 0)
    received = m.get("received", {}).get("quantity", 0)
    damaged = m.get("damaged", {}).get("quantity", 0)
    returned = m.get("returned", {}).get("quantity", 0)
    return f"Today's summary\n• Units sold: {sold}\n• Units received: {received}\n• Units damaged: {damaged}\n• Units returned: {returned}"

def daily_report(db_path, day=None):
    day = day or date.today().isoformat()
    try:
        parsed = date.fromisoformat(day)
    except ValueError:
        raise ValidationError("Date must use YYYY-MM-DD.")
    conn = get_db(db_path)
    try:
        summary = _daily_summary_conn(conn, parsed.isoformat())
        products = conn.execute("SELECT name, quantity, unit, min_stock FROM products ORDER BY name COLLATE NOCASE").fetchall()
        balances = conn.execute("SELECT name, outstanding_balance_paise FROM customers ORDER BY name COLLATE NOCASE").fetchall()
        summary["stock_overview"] = [dict(r) for r in products]
        summary["outstanding_balances"] = [{"name": r["name"], "balance_paise": r["outstanding_balance_paise"]} for r in balances]
        return summary
    finally:
        conn.close()

def supplier_message(db_path):
    conn = get_db(db_path)
    try:
        rows = conn.execute("SELECT name, quantity, unit, min_stock FROM products WHERE quantity <= min_stock ORDER BY name COLLATE NOCASE").fetchall()
        if not rows:
            return "No items currently need reordering."
        lines = [f"- {r['name']}: {max(r['min_stock'] * 2 - r['quantity'], 1)} {r['unit']}" for r in rows]
        return "Hello, please send the following items:\n" + "\n".join(lines) + "\nThank you."
    finally:
        conn.close()

def list_inventory_transactions(db_path, limit=100):
    conn = get_db(db_path)
    try:
        rows = conn.execute("""SELECT t.*, p.name AS product_name, p.unit FROM inventory_transactions t
            JOIN products p ON p.id=t.product_id ORDER BY t.id DESC LIMIT ?""", (min(max(int(limit), 1), 250),)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
