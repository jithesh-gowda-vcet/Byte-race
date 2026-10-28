from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from pathlib import Path
import os
import re
from database import init_db, get_db
from services import (
    process_chat, list_products, create_product, update_product,
    list_customers, create_customer, customer_transactions,
    record_credit, dashboard_data, daily_report, low_stock_products,
    supplier_message, list_inventory_transactions, ValidationError, NotFoundError
)

BASE_DIR = Path(__file__).resolve().parent

def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        DATABASE=os.environ.get("DUKAANMITRA_DATABASE", str(Path(app.instance_path) / "dukaanmitra.sqlite3")),
        JSON_SORT_KEYS=False,
    )
    if test_config:
        app.config.update(test_config)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    init_db(app.config["DATABASE"])

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "app": "DukaanMitra"})

    @app.get("/api/dashboard")
    def dashboard():
        return jsonify(dashboard_data(app.config["DATABASE"]))

    @app.get("/api/products")
    def products():
        q = request.args.get("q", "").strip()
        low = request.args.get("low_stock", "").lower() in ("1", "true", "yes")
        return jsonify({"products": list_products(app.config["DATABASE"], q=q, low_stock=low)})

    @app.post("/api/products")
    def products_create():
        data = json_body()
        return jsonify({"product": create_product(app.config["DATABASE"], data)}), 201

    @app.patch("/api/products/<int:product_id>")
    def products_update(product_id):
        return jsonify({"product": update_product(app.config["DATABASE"], product_id, json_body())})

    @app.post("/api/products/<int:product_id>/adjust")
    def products_adjust(product_id):
        data = json_body()
        message = f"adjust {data.get('quantity')} {data.get('product', '')}".strip()
        # Use a dedicated adjustment endpoint to preserve explicit product ID.
        from services import adjust_stock
        return jsonify(adjust_stock(app.config["DATABASE"], product_id, data))

    @app.get("/api/transactions")
    def transactions():
        return jsonify({"transactions": list_inventory_transactions(app.config["DATABASE"], limit=100)})

    @app.post("/api/chat")
    def chat():
        data = json_body()
        message = data.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ValidationError("Enter a message first.")
        result = process_chat(app.config["DATABASE"], message.strip())
        return jsonify(result), (200 if result.get("ok") else 422)

    @app.get("/api/customers")
    def customers():
        return jsonify({"customers": list_customers(app.config["DATABASE"], request.args.get("q", "").strip())})

    @app.post("/api/customers")
    def customers_create():
    data = json_body()
    # Validate Indian mobile number
    phone = str(data.get("phone", "")).strip()
    if not re.fullmatch(r"[6-9]\d{9}", phone):
        raise ValidationError( "Enter a valid 10-digit Indian mobile number starting with 6, 7, 8, or 9.")
    customer = create_customer(app.config["DATABASE"], data)
    return jsonify({"customer": customer}), 201
    
    @app.get("/api/customers/<int:customer_id>/transactions")
    def customer_txns(customer_id):
        return jsonify({"transactions": customer_transactions(app.config["DATABASE"], customer_id)})

    @app.post("/api/credit")
    def credit():
        return jsonify(record_credit(app.config["DATABASE"], json_body()))

    @app.get("/api/reports/daily")
    def reports_daily():
        return jsonify(daily_report(app.config["DATABASE"], request.args.get("date")))

    @app.get("/api/low-stock")
    def low_stock():
        products = low_stock_products(app.config["DATABASE"])
        return jsonify({"products": products, "count": len(products)})

    @app.get("/api/supplier-message")
    def supplier():
        return jsonify({"message": supplier_message(app.config["DATABASE"])})

    @app.errorhandler(ValidationError)
    def validation_error(exc):
        return jsonify({"ok": False, "error": str(exc)}), 400

    @app.errorhandler(NotFoundError)
    def not_found(exc):
        return jsonify({"ok": False, "error": str(exc)}), 404

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify({"ok": False, "error": exc.description}), exc.code

    @app.errorhandler(Exception)
    def unexpected_error(exc):
        app.logger.exception("Unhandled application error")
        return jsonify({"ok": False, "error": "Something went wrong. Please try again."}), 500

    return app

def json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object.")
    return data

app = create_app()

if __name__ == "__main__":
    # Debug stays off by default. Set FLASK_DEBUG=1 only for local development.
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=os.environ.get("FLASK_DEBUG") == "1")
