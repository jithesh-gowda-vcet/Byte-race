import tempfile
import unittest
import importlib.util
from pathlib import Path
from database import init_db, get_db
from services import process_chat, dashboard_data, daily_report, supplier_message, create_product, create_customer, record_credit

class DukaanMitraTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self.tmp.name) / "test.sqlite3")
        init_db(self.db)

    def tearDown(self):
        self.tmp.cleanup()

    def product_qty(self, name):
        c = get_db(self.db)
        try:
            row = c.execute("SELECT quantity FROM products WHERE normalized_name=?", (name.casefold(),)).fetchone()
            return row["quantity"]
        finally:
            c.close()

    def balance(self, name="ramesh"):
        c = get_db(self.db)
        try:
            row = c.execute("SELECT outstanding_balance_paise FROM customers WHERE normalized_name=?", (name,)).fetchone()
            return row["outstanding_balance_paise"]
        finally:
            c.close()

    def test_sell_one_product(self):
        before = self.product_qty("maggi")
        r = process_chat(self.db, "sold 3 Maggi")
        self.assertTrue(r["ok"])
        self.assertEqual(self.product_qty("maggi"), before-3)

    def test_sell_multiple_products(self):
        before_m, before_milk = self.product_qty("maggi"), self.product_qty("milk")
        r = process_chat(self.db, "sold 3 Maggi, 2 milk")
        self.assertTrue(r["ok"])
        self.assertEqual(self.product_qty("maggi"), before_m-3)
        self.assertEqual(self.product_qty("milk"), before_milk-2)

    def test_receive_stock(self):
        before = self.product_qty("rice")
        self.assertTrue(process_chat(self.db, "received 20 rice")["ok"])
        self.assertEqual(self.product_qty("rice"), before+20)

    def test_damaged_goods(self):
        before = self.product_qty("cooking oil")
        self.assertTrue(process_chat(self.db, "damaged 1 cooking oil")["ok"])
        self.assertEqual(self.product_qty("cooking oil"), before-1)

    def test_customer_return(self):
        before = self.product_qty("milk")
        self.assertTrue(process_chat(self.db, "returned 2 milk")["ok"])
        self.assertEqual(self.product_qty("milk"), before+2)

    def test_reject_sale_over_stock(self):
        before = self.product_qty("maggi")
        r = process_chat(self.db, "sold 999 Maggi")
        self.assertFalse(r["ok"])
        self.assertEqual(self.product_qty("maggi"), before)

    def test_reject_unknown_product(self):
        before = self.product_qty("maggi")
        r = process_chat(self.db, "sold 2 unicorn noodles")
        self.assertFalse(r["ok"])
        self.assertEqual(self.product_qty("maggi"), before)

    def test_reject_negative_and_malformed_quantities(self):
        for msg in ("sold -2 Maggi", "sold zero Maggi", "sold 0 Maggi", "sold 2"):
            with self.subTest(msg=msg):
                before = self.product_qty("maggi")
                self.assertFalse(process_chat(self.db, msg)["ok"])
                self.assertEqual(self.product_qty("maggi"), before)

    def test_invalid_multi_item_is_atomic(self):
        before_m, before_milk = self.product_qty("maggi"), self.product_qty("milk")
        r = process_chat(self.db, "sold 3 Maggi, 999 milk")
        self.assertFalse(r["ok"])
        self.assertEqual(self.product_qty("maggi"), before_m)
        self.assertEqual(self.product_qty("milk"), before_milk)

    def test_persistence_after_reconnect(self):
        process_chat(self.db, "sold 2 Maggi")
        self.assertEqual(self.product_qty("maggi"), 38)

    def test_low_stock_calculation(self):
        process_chat(self.db, "sold 30 Maggi")
        d = dashboard_data(self.db)
        self.assertIn("Maggi", [p["name"] for p in d["low_stock_products"]])

    def test_credit_purchase_reduces_stock_and_increases_balance(self):
        before_stock, before_balance = self.product_qty("rice"), self.balance()
        r = process_chat(self.db, "Ramesh took 2 rice on credit")
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.product_qty("rice"), before_stock-2)
        self.assertEqual(self.balance(), before_balance+13000)

    def test_payment_reduces_balance_and_not_stock(self):
        process_chat(self.db, "Ramesh took 2 rice on credit")
        before_stock, before_balance = self.product_qty("rice"), self.balance()
        r = process_chat(self.db, "Ramesh paid 100")
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.balance(), before_balance-10000)
        self.assertEqual(self.product_qty("rice"), before_stock)

    def test_daily_summary_shape(self):
        process_chat(self.db, "sold 3 Maggi")
        report = daily_report(self.db)
        self.assertIn("inventory_movements", report)
        self.assertGreaterEqual(report["inventory_movements"]["sold"]["quantity"], 3)

    def test_supplier_message_uses_low_stock(self):
        process_chat(self.db, "sold 35 Maggi")
        msg = supplier_message(self.db)
        self.assertIn("Maggi", msg)
        self.assertIn("packets", msg)

    @unittest.skipUnless(importlib.util.find_spec("flask"), "Flask dependency is not installed in this environment")
    def test_flask_api_health_and_chat(self):
        from app import create_app
        app = create_app({"TESTING": True, "DATABASE": self.db})
        client = app.test_client()
        self.assertEqual(client.get("/api/health").status_code, 200)
        res = client.post("/api/chat", json={"message": "sold 1 Maggi"})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ok"])

if __name__ == "__main__":
    unittest.main()
