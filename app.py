
import os
import re
import sqlite3
import uuid

from pathlib import Path
from functools import wraps

from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    session,
    g,
)
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash, check_password_hash

from database import init_db
from services import (
    process_chat,
    list_products,
    create_product,
    update_product,
    list_customers,
    create_customer,
    customer_transactions,
    record_credit,
    dashboard_data,
    daily_report,
    low_stock_products,
    supplier_message,
    list_inventory_transactions,
    ValidationError,
    NotFoundError,
)


# ---------------------------------------------------------
# Application configuration
# ---------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)

    app.config.from_mapping(
        SECRET_KEY=os.environ.get("DUKAANMITRA_SECRET_KEY"),
        AUTH_DATABASE=os.environ.get(
            "DUKAANMITRA_AUTH_DATABASE",
            str(Path(app.instance_path) / "accounts.sqlite3"),
        ),
        SHOP_DATABASE_DIR=os.environ.get(
            "DUKAANMITRA_SHOP_DATABASE_DIR",
            str(Path(app.instance_path) / "shops"),
        ),
        DATABASE=os.environ.get(
            "DUKAANMITRA_DATABASE",
            str(Path(app.instance_path) / "dukaanmitra.sqlite3"),
        ),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get(
            "DUKAANMITRA_COOKIE_SECURE", "0"
        ).lower() in ("1", "true", "yes"),
        PERMANENT_SESSION_LIFETIME=60 * 60 * 8,
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
        JSON_SORT_KEYS=False,
    )

    if test_config:
        app.config.update(test_config)

    if not app.config["SECRET_KEY"]:
        if os.environ.get("FLASK_DEBUG") == "1":
            app.config["SECRET_KEY"] = (
                "local-development-only-change-me"
            )
        else:
            raise RuntimeError(
                "Set DUKAANMITRA_SECRET_KEY before starting the app."
            )

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    Path(app.config["SHOP_DATABASE_DIR"]).mkdir(
        parents=True, exist_ok=True
    )

    auth_path = Path(app.config["AUTH_DATABASE"])
    auth_path.parent.mkdir(parents=True, exist_ok=True)

    init_auth_database(app.config["AUTH_DATABASE"])

    # -----------------------------------------------------
    # Authentication database
    # -----------------------------------------------------

    #def init_auth_database(database_path):
        # This function is defined below at module level.
        # The module-level function is used by this application.
        #pass

    # -----------------------------------------------------
    # Request helpers
    # -----------------------------------------------------

    def json_body():
        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            raise ValidationError(
                "Request body must be a JSON object."
            )

        return data

    def auth_connection():
        connection = sqlite3.connect(
            app.config["AUTH_DATABASE"],
            timeout=10,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def get_shop_database(shop_id):
        """Resolve a shop database from a trusted shop ID."""
        if not isinstance(shop_id, int) or shop_id < 1:
            raise ValidationError("Invalid shop account.")

        with auth_connection() as connection:
            shop = connection.execute(
                """
                SELECT database_filename
                FROM shops
                WHERE id = ?
                """,
                (shop_id,),
            ).fetchone()

        if shop is None:
            raise NotFoundError("Shop not found.")

        filename = shop["database_filename"]

        # Never accept a filesystem path supplied by the client.
        if not re.fullmatch(r"[a-f0-9]{32}\.sqlite3", filename):
            app.logger.error("Invalid shop database filename.")
            raise RuntimeError("Invalid shop database configuration.")

        database_dir = Path(
            app.config["SHOP_DATABASE_DIR"]
        ).resolve()

        database_path = (
            database_dir / filename
        ).resolve()

        if database_path.parent != database_dir:
            raise RuntimeError("Invalid shop database path.")

        if not database_path.is_file():
            raise RuntimeError("Shop database is not initialized.")

        return str(database_path)

    def current_user():
        user_id = session.get("user_id")

        if not user_id:
            return None

        with auth_connection() as connection:
            user = connection.execute(
                """
                SELECT id, phone, role, shop_id
                FROM users
                WHERE id = ? AND is_active = 1
                """,
                (user_id,),
            ).fetchone()

        if user is None:
            session.clear()
            return None

        return dict(user)

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()

            if user is None:
                return jsonify({
                    "ok": False,
                    "error": "Please log in to continue.",
                }), 401

            g.current_user = user

            return view(*args, **kwargs)

        return wrapped

    def owner_required(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.current_user["role"] != "owner":
                return jsonify({
                    "ok": False,
                    "error": "Shop owner access required.",
                }), 403

            shop_id = g.current_user["shop_id"]

            if shop_id is None:
                return jsonify({
                    "ok": False,
                    "error": "No shop is associated with this account.",
                }), 403

            g.shop_database = get_shop_database(shop_id)

            return view(*args, **kwargs)

        return wrapped

    def admin_required(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.current_user["role"] != "admin":
                return jsonify({
                    "ok": False,
                    "error": "Administrator access required.",
                }), 403

            return view(*args, **kwargs)

        return wrapped

    # -----------------------------------------------------
    # Public pages
    # -----------------------------------------------------

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/health")
    def health():
        return jsonify({
            "status": "ok",
            "app": "DukaanMitra",
        })

    # -----------------------------------------------------
    # Registration
    # -----------------------------------------------------

    @app.post("/api/auth/register")
    def register():
        data = json_body()

        phone = str(data.get("phone", "")).strip()
        password = data.get("password", "")
        shop_name = str(
            data.get("shop_name", "")
        ).strip()

        if not re.fullmatch(r"[6-9]\d{9}", phone):
            raise ValidationError(
                "Enter a valid 10-digit Indian mobile number."
            )

        if not isinstance(password, str) or len(password) < 8:
            raise ValidationError(
                "Password must contain at least 8 characters."
            )

        if len(password) > 128:
            raise ValidationError("Password is too long.")

        if not shop_name or len(shop_name) > 120:
            raise ValidationError(
                "Enter a shop name of 1 to 120 characters."
            )

        password_hash = generate_password_hash(password)
        database_filename = f"{uuid.uuid4().hex}.sqlite3"
        database_path = (
            Path(app.config["SHOP_DATABASE_DIR"])
            / database_filename
        )

        # Check for an existing account before initializing a shop.
        with auth_connection() as connection:
            existing = connection.execute(
                "SELECT id FROM users WHERE phone = ?",
                (phone,),
            ).fetchone()

        if existing:
            return jsonify({
                "ok": False,
                "error": "An account with this phone number already exists.",
            }), 409

        # Initialize a separate database for the new shop.
        init_db(str(database_path))

        try:
            with auth_connection() as connection:
                connection.execute("BEGIN IMMEDIATE")

                existing = connection.execute(
                    "SELECT id FROM users WHERE phone = ?",
                    (phone,),
                ).fetchone()

                if existing:
                    raise ValidationError(
                        "An account with this phone number already exists."
                    )

                cursor = connection.execute(
                    """
                    INSERT INTO shops (
                        name,
                        database_filename
                    )
                    VALUES (?, ?)
                    """,
                    (shop_name, database_filename),
                )

                shop_id = cursor.lastrowid

                cursor = connection.execute(
                    """
                    INSERT INTO users (
                        phone,
                        password_hash,
                        role,
                        shop_id,
                        is_active
                    )
                    VALUES (?, ?, 'owner', ?, 1)
                    """,
                    (phone, password_hash, shop_id),
                )

                user_id = cursor.lastrowid

        except ValidationError:
            # Remove the newly created database if registration fails.
            if database_path.exists():
                database_path.unlink()
            raise

        except sqlite3.IntegrityError:
            if database_path.exists():
                database_path.unlink()

            return jsonify({
                "ok": False,
                "error": "This account could not be created. Check whether the phone number is already registered.",
            }), 409

        session.clear()
        session["user_id"] = user_id
        session.permanent = True

        return jsonify({
            "ok": True,
            "message": "Account created successfully.",
            "user": {
                "id": user_id,
                "phone": phone,
                "role": "owner",
                "shop_id": shop_id,
                "shop_name": shop_name,
            },
        }), 201

    # -----------------------------------------------------
    # Login and logout
    # -----------------------------------------------------

    @app.post("/api/auth/login")
    def login():
        data = json_body()

        phone = str(data.get("phone", "")).strip()
        password = data.get("password", "")

        if not isinstance(password, str) or not password:
            raise ValidationError("Enter your password.")

        with auth_connection() as connection:
            user = connection.execute(
                """
                SELECT id, phone, password_hash, role, shop_id
                FROM users
                WHERE phone = ? AND is_active = 1
                """,
                (phone,),
            ).fetchone()

        if user is None or not check_password_hash(
            user["password_hash"], password
        ):
            return jsonify({
                "ok": False,
                "error": "Invalid phone number or password.",
            }), 401

        session.clear()
        session["user_id"] = user["id"]
        session.permanent = True

        return jsonify({
            "ok": True,
            "message": "Login successful.",
            "user": {
                "id": user["id"],
                "phone": user["phone"],
                "role": user["role"],
                "shop_id": user["shop_id"],
            },
        })

    @app.post("/api/auth/logout")
    def logout():
        session.clear()

        return jsonify({
            "ok": True,
            "message": "Logged out successfully.",
        })

    @app.get("/api/auth/me")
    @login_required
    def me():
        return jsonify({
            "ok": True,
            "user": g.current_user,
        })

    # -----------------------------------------------------
    # Administrator endpoints
    # -----------------------------------------------------

    @app.get("/api/admin/shops")
    @admin_required
    def admin_shops():
        with auth_connection() as connection:
            shops = connection.execute(
                """
                SELECT
                    s.id,
                    s.name,
                    s.created_at,
                    u.phone AS owner_phone
                FROM shops s
                LEFT JOIN users u
                    ON u.shop_id = s.id
                    AND u.role = 'owner'
                ORDER BY s.id DESC
                """
            ).fetchall()

        return jsonify({
            "shops": [dict(shop) for shop in shops]
        })

    @app.get("/api/admin/users")
    @admin_required
    def admin_users():
        with auth_connection() as connection:
            users = connection.execute(
                """
                SELECT id, phone, role, shop_id, is_active
                FROM users
                ORDER BY id DESC
                """
            ).fetchall()

        return jsonify({
            "users": [dict(user) for user in users]
        })

    # -----------------------------------------------------
    # Dashboard
    # -----------------------------------------------------

    @app.get("/api/dashboard")
    @owner_required
    def dashboard():
        return jsonify(dashboard_data(g.shop_database))

    # -----------------------------------------------------
    # Products and inventory
    # -----------------------------------------------------

    @app.get("/api/products")
    @owner_required
    def products():
        query = request.args.get("q", "").strip()
        low_stock = request.args.get(
            "low_stock", ""
        ).lower() in ("1", "true", "yes")

        return jsonify({
            "products": list_products(
                g.shop_database,
                q=query,
                low_stock=low_stock,
            )
        })

    @app.post("/api/products")
    @owner_required
    def products_create():
        product = create_product(
            g.shop_database,
            json_body(),
        )

        return jsonify({"product": product}), 201

    @app.patch("/api/products/<int:product_id>")
    @owner_required
    def products_update(product_id):
        product = update_product(
            g.shop_database,
            product_id,
            json_body(),
        )

        return jsonify({"product": product})

    @app.post("/api/products/<int:product_id>/adjust")
    @owner_required
    def products_adjust(product_id):
        from services import adjust_stock

        result = adjust_stock(
            g.shop_database,
            product_id,
            json_body(),
        )

        return jsonify(result)

    @app.get("/api/transactions")
    @owner_required
    def transactions():
        return jsonify({
            "transactions": list_inventory_transactions(
                g.shop_database,
                limit=100,
            )
        })

    # -----------------------------------------------------
    # Chat
    # -----------------------------------------------------

    @app.post("/api/chat")
    @owner_required
    def chat():
        data = json_body()
        message = data.get("message")

        if not isinstance(message, str) or not message.strip():
            raise ValidationError("Enter a message first.")

        result = process_chat(
            g.shop_database,
            message.strip(),
        )

        return jsonify(result), (
            200 if result.get("ok") else 422
        )

    # -----------------------------------------------------
    # Customers
    # -----------------------------------------------------

    @app.get("/api/customers")
    @owner_required
    def customers():
        query = request.args.get("q", "").strip()

        return jsonify({
            "customers": list_customers(
                g.shop_database,
                query,
            )
        })

    @app.post("/api/customers")
    @owner_required
    def customers_create():
        data = json_body()
        phone = str(data.get("phone", "")).strip()

        if not re.fullmatch(r"[6-9]\d{9}", phone):
            raise ValidationError(
                "Enter a valid 10-digit Indian mobile number starting with 6, 7, 8, or 9."
            )

        customer = create_customer(
            g.shop_database,
            data,
        )

        return jsonify({"customer": customer}), 201

    @app.get(
        "/api/customers/<int:customer_id>/transactions"
    )
    @owner_required
    def customer_txns(customer_id):
        return jsonify({
            "transactions": customer_transactions(
                g.shop_database,
                customer_id,
            )
        })

    # -----------------------------------------------------
    # Customer credit
    # -----------------------------------------------------

    @app.post("/api/credit")
    @owner_required
    def credit():
        result = record_credit(
            g.shop_database,
            json_body(),
        )

        return jsonify(result)

    # -----------------------------------------------------
    # Reports and supplier messages
    # -----------------------------------------------------

    @app.get("/api/reports/daily")
    @owner_required
    def reports_daily():
        return jsonify(
            daily_report(
                g.shop_database,
                request.args.get("date"),
            )
        )

    @app.get("/api/low-stock")
    @owner_required
    def low_stock():
        products = low_stock_products(g.shop_database)

        return jsonify({
            "products": products,
            "count": len(products),
        })

    @app.get("/api/supplier-message")
    @owner_required
    def supplier():
        return jsonify({
            "message": supplier_message(g.shop_database)
        })

    # -----------------------------------------------------
    # Error handling
    # -----------------------------------------------------

    @app.errorhandler(ValidationError)
    def validation_error(exc):
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 400

    @app.errorhandler(NotFoundError)
    def not_found(exc):
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 404

    @app.errorhandler(HTTPException)
    def http_error(exc):
        return jsonify({
            "ok": False,
            "error": exc.description,
        }), exc.code

    @app.errorhandler(Exception)
    def unexpected_error(exc):
        app.logger.exception("Unhandled application error")

        return jsonify({
            "ok": False,
            "error": "Something went wrong. Please try again.",
        }), 500

    return app


# ---------------------------------------------------------
# Authentication database initialization
# ---------------------------------------------------------

def init_auth_database(database_path):
    """Create account and shop tables if they do not exist."""
    connection = sqlite3.connect(database_path)

    try:
        connection.execute("PRAGMA foreign_keys = ON")

        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS shops (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                database_filename TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'owner'
                    CHECK (role IN ('owner', 'admin')),
                shop_id INTEGER,
                is_active INTEGER NOT NULL DEFAULT 1
                    CHECK (is_active IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (shop_id)
                    REFERENCES shops(id)
            );

            CREATE INDEX IF NOT EXISTS idx_users_shop_id
                ON users(shop_id);

            CREATE INDEX IF NOT EXISTS idx_users_role
                ON users(role);
            """
        )

        connection.commit()

    finally:
        connection.close()


# ---------------------------------------------------------
# Application entry point
# ---------------------------------------------------------

app = create_app()

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG") == "1"

    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5000")),
        debug=debug,
    )
