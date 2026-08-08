from __future__ import annotations

import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "ecocredit.db"
PLATFORM_FEE_RATE = 0.05

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-demo-secret-before-deploying")


def get_db() -> sqlite3.Connection:
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    return db


def current_user() -> sqlite3.Row | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    with closing(get_db()) as db:
        return db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def add_notification(db: sqlite3.Connection, user_id: int, message: str, kind: str = "general", request_id: int | None = None) -> None:
    db.execute(
        "INSERT INTO notifications (user_id, message, kind, request_id) VALUES (?, ?, ?, ?)",
        (user_id, message, kind, request_id),
    )


def request_for_member(db: sqlite3.Connection, request_id: int, user_id: int) -> sqlite3.Row | None:
    return db.execute(
        """SELECT r.*, i.title, i.listing_type, i.rupees, i.points, i.owner_id, i.platform_fee,
                  i.exchange_deadline, u.name AS seller_name
           FROM swap_requests r
           JOIN items i ON i.id = r.item_id
           JOIN users u ON u.id = i.owner_id
           WHERE r.id = ? AND (r.requester_id = ? OR i.owner_id = ?)""",
        (request_id, user_id, user_id),
    ).fetchone()


def seed_database() -> None:
    with closing(get_db()) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
                hostel TEXT NOT NULL DEFAULT 'Hostel A', eco_points INTEGER NOT NULL DEFAULT 120,
                rating_total INTEGER NOT NULL DEFAULT 0, rating_count INTEGER NOT NULL DEFAULT 0,
                wallet_balance INTEGER NOT NULL DEFAULT 0, upi_id TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL, category TEXT NOT NULL, item_condition TEXT NOT NULL,
                location TEXT NOT NULL, points INTEGER NOT NULL, emoji TEXT NOT NULL,
                description TEXT NOT NULL, owner_name TEXT NOT NULL, is_available INTEGER NOT NULL DEFAULT 1,
                listing_type TEXT NOT NULL DEFAULT 'swap', rupees INTEGER, image_data TEXT DEFAULT '',
                actual_price INTEGER, exchange_deadline TEXT, owner_id INTEGER,
                platform_fee INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS swap_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER NOT NULL, requester_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', payment_status TEXT NOT NULL DEFAULT 'not_required',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(item_id) REFERENCES items(id), FOREIGN KEY(requester_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, request_id INTEGER NOT NULL, sender_id INTEGER NOT NULL,
                body TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT, request_id INTEGER NOT NULL, rater_id INTEGER NOT NULL,
                score INTEGER NOT NULL, UNIQUE(request_id, rater_id)
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, message TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'general', request_id INTEGER, read_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS wallet_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, amount INTEGER NOT NULL,
                transaction_type TEXT NOT NULL, note TEXT NOT NULL, request_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
        user_columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
        for column, definition in (("wallet_balance", "INTEGER NOT NULL DEFAULT 0"), ("upi_id", "TEXT DEFAULT ''")):
            if column not in user_columns:
                db.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")
        request_columns = {row[1] for row in db.execute("PRAGMA table_info(swap_requests)")}
        if "payment_status" not in request_columns:
            db.execute("ALTER TABLE swap_requests ADD COLUMN payment_status TEXT NOT NULL DEFAULT 'not_required'")
        item_columns = {row[1] for row in db.execute("PRAGMA table_info(items)")}
        for column, definition in (("listing_type", "TEXT NOT NULL DEFAULT 'swap'"), ("rupees", "INTEGER"), ("image_data", "TEXT DEFAULT ''"), ("actual_price", "INTEGER"), ("exchange_deadline", "TEXT"), ("owner_id", "INTEGER"), ("platform_fee", "INTEGER NOT NULL DEFAULT 0")):
            if column not in item_columns:
                db.execute(f"ALTER TABLE items ADD COLUMN {column} {definition}")
        if db.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0:
            demo_items = [
                ("First-year CSE books", "Study", "Like new", "Library Block", 120, "📚", "Programming, maths and engineering basics.", "Riya S."),
                ("Hostel essentials kit", "Hostel", "Good", "Hostel C", 40, "🪣", "Bucket, mug and clothes hangers.", "Karan M."),
                ("Wired headphones", "Tech", "Excellent", "Campus Cafe", 55, "🎧", "Working perfectly. 3.5 mm jack.", "Aman J."),
            ]
            db.executemany("""INSERT INTO items (title, category, item_condition, location, points, emoji, description, owner_name)
                              VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", demo_items)
        db.commit()


seed_database()


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/api/items")
def list_items():
    category, search = request.args.get("category", "All"), request.args.get("search", "").strip()
    query, values = "SELECT * FROM items WHERE is_available = 1", []
    if category != "All":
        query += " AND category = ?"; values.append(category)
    if search:
        query += " AND (title LIKE ? OR description LIKE ? OR category LIKE ?)"; values.extend([f"%{search}%"] * 3)
    query += " ORDER BY id DESC"
    with closing(get_db()) as db:
        return jsonify([dict(row) for row in db.execute(query, values).fetchall()])


@app.get("/api/me")
def me():
    user = current_user()
    return jsonify({"logged_in": bool(user), "user": dict(user) if user else None})


@app.post("/api/auth/signup")
def signup():
    data = request.get_json(silent=True) or {}
    email, password = data.get("email", "").strip().lower(), data.get("password", "")
    name, hostel = data.get("name", "").strip(), data.get("hostel", "").strip()
    if not name or not hostel or "@" not in email or len(password) < 4:
        return jsonify({"error": "Enter your name, campus area, valid college email, and a 4-character password."}), 400
    with closing(get_db()) as db:
        if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            return jsonify({"error": "An account already exists for this email. Please log in."}), 409
        cursor = db.execute("INSERT INTO users (name, email, password_hash, hostel) VALUES (?, ?, ?, ?)", (name, email, generate_password_hash(password), hostel))
        user = db.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone(); db.commit()
    session["user_id"] = user["id"]
    return jsonify({"user": dict(user)})


@app.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    with closing(get_db()) as db:
        user = db.execute("SELECT * FROM users WHERE email = ?", (data.get("email", "").strip().lower(),)).fetchone()
    if not user or not check_password_hash(user["password_hash"], data.get("password", "")):
        return jsonify({"error": "Incorrect email or password."}), 401
    session["user_id"] = user["id"]
    return jsonify({"user": dict(user)})


@app.post("/api/auth/logout")
def logout():
    session.clear(); return jsonify({"ok": True})


@app.post("/api/items")
def create_item():
    user, data = current_user(), request.get_json(silent=True) or {}
    if not user: return jsonify({"error": "Please log in first."}), 401
    required = ("title", "category", "condition", "location", "listing_type", "actual_price")
    if any(not str(data.get(field, "")).strip() for field in required): return jsonify({"error": "Please complete all item details."}), 400
    listing_type = data["listing_type"]
    try: actual_price, points, rupees = int(data["actual_price"]), int(data.get("points") or 0), int(data.get("rupees") or 0)
    except (TypeError, ValueError): return jsonify({"error": "Prices must be whole numbers."}), 400
    if listing_type not in ("swap", "sell") or actual_price < 1 or (listing_type == "swap" and points < 1) or (listing_type == "sell" and rupees < 1):
        return jsonify({"error": "Enter a valid price for the selected listing type."}), 400
    image_data = data.get("image_data", "")
    if image_data and not image_data.startswith("data:image/"): return jsonify({"error": "Please upload an image file."}), 400
    fee = round(rupees * PLATFORM_FEE_RATE) if listing_type == "sell" else 0
    with closing(get_db()) as db:
        db.execute("""INSERT INTO items (title, category, item_condition, location, points, emoji, description, owner_name, listing_type, rupees, image_data, actual_price, exchange_deadline, owner_id, platform_fee)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', '+7 days'), ?, ?)""",
                   (data["title"].strip(), data["category"], data["condition"].strip(), data["location"].strip(), points, data.get("emoji", "♻️"), data.get("description", "A useful campus item."), user["name"], listing_type, rupees if listing_type == "sell" else None, image_data, actual_price, user["id"], fee))
        db.execute("UPDATE users SET eco_points = eco_points + 10 WHERE id = ?", (user["id"],)); db.commit()
    return jsonify({"message": "Item listed! You earned 10 Eco Points."}), 201


@app.post("/api/items/<int:item_id>/request")
def request_swap(item_id: int):
    user = current_user()
    if not user: return jsonify({"error": "Please log in first."}), 401
    with closing(get_db()) as db:
        item = db.execute("SELECT * FROM items WHERE id = ? AND is_available = 1 AND (exchange_deadline IS NULL OR exchange_deadline > datetime('now'))", (item_id,)).fetchone()
        if not item: return jsonify({"error": "This item is unavailable or its one-week exchange window has ended."}), 404
        if item["owner_id"] == user["id"]: return jsonify({"error": "You cannot request your own listing."}), 400
        if db.execute("SELECT 1 FROM swap_requests WHERE item_id = ? AND requester_id = ?", (item_id, user["id"])).fetchone(): return jsonify({"error": "You have already requested this item."}), 409
        db.execute("INSERT INTO swap_requests (item_id, requester_id) VALUES (?, ?)", (item_id, user["id"]))
        request_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        if item["owner_id"]: add_notification(db, item["owner_id"], f"You received a request for {item['title']}.", "request", request_id)
        db.commit()
    return jsonify({"message": "Request sent. You will be notified when the owner responds."}), 201


@app.get("/api/stats")
def stats():
    with closing(get_db()) as db:
        items, requests = db.execute("SELECT COUNT(*) FROM items").fetchone()[0], db.execute("SELECT COUNT(*) FROM swap_requests").fetchone()[0]
    return jsonify({"waste_prevented": 286 + items * 2, "items_reused": 1248 + items, "student_savings": "₹ 1.8L", "requests": requests})


@app.get("/api/profile")
def profile():
    user = current_user()
    if not user: return jsonify({"error": "Please log in first."}), 401
    with closing(get_db()) as db:
        listings = db.execute("SELECT * FROM items WHERE owner_id = ? ORDER BY id DESC", (user["id"],)).fetchall()
        requests = db.execute("""SELECT r.*, i.title, i.listing_type, i.rupees, i.points, i.owner_id, i.platform_fee, i.location
                               FROM swap_requests r JOIN items i ON i.id = r.item_id WHERE r.requester_id = ? ORDER BY r.created_at DESC""", (user["id"],)).fetchall()
    rating = round(user["rating_total"] / user["rating_count"], 1) if user["rating_count"] else None
    request_data = []
    for row in requests:
        item = dict(row)
        # The pickup point for a paid listing is private until funds are held in escrow.
        item["pickup_location"] = item["location"] if item["listing_type"] == "sell" and item["payment_status"] in ("held", "released") else None
        item.pop("location", None)
        request_data.append(item)
    return jsonify({"user": {**dict(user), "rating": rating}, "listings": [dict(x) for x in listings], "requests": request_data})


@app.put("/api/profile")
def update_profile():
    user, data = current_user(), request.get_json(silent=True) or {}
    if not user: return jsonify({"error": "Please log in first."}), 401
    name, hostel, upi_id = data.get("name", "").strip(), data.get("hostel", "").strip(), data.get("upi_id", "").strip()
    if not name or not hostel: return jsonify({"error": "Name and campus area are required."}), 400
    if upi_id and not re.fullmatch(r"[\w.\-]{2,256}@[\w.\-]{2,64}", upi_id): return jsonify({"error": "Enter a valid UPI ID, for example name@bank."}), 400
    with closing(get_db()) as db:
        db.execute("UPDATE users SET name = ?, hostel = ?, upi_id = ? WHERE id = ?", (name, hostel, upi_id, user["id"]))
        db.execute("UPDATE items SET owner_name = ? WHERE owner_id = ?", (name, user["id"])); db.commit()
    return jsonify({"message": "Profile updated."})


@app.get("/api/wallet")
def wallet():
    user = current_user()
    if not user: return jsonify({"error": "Please log in first."}), 401
    with closing(get_db()) as db:
        fresh = db.execute("SELECT wallet_balance, upi_id FROM users WHERE id = ?", (user["id"],)).fetchone()
        transactions = db.execute("SELECT * FROM wallet_transactions WHERE user_id = ? ORDER BY id DESC LIMIT 12", (user["id"],)).fetchall()
    return jsonify({"balance": fresh["wallet_balance"], "upi_id": fresh["upi_id"], "transactions": [dict(x) for x in transactions], "demo_mode": True})


@app.post("/api/wallet/add-money")
def add_money():
    user, data = current_user(), request.get_json(silent=True) or {}
    if not user: return jsonify({"error": "Please log in first."}), 401
    try: amount = int(data.get("amount", 0))
    except (TypeError, ValueError): amount = 0
    if not 10 <= amount <= 50000: return jsonify({"error": "Add an amount from ₹10 to ₹50,000."}), 400
    with closing(get_db()) as db:
        db.execute("UPDATE users SET wallet_balance = wallet_balance + ? WHERE id = ?", (amount, user["id"]))
        db.execute("INSERT INTO wallet_transactions (user_id, amount, transaction_type, note) VALUES (?, ?, 'add_money', 'Demo wallet top-up')", (user["id"], amount))
        add_notification(db, user["id"], f"₹{amount} was added to your EcoCredit wallet.", "wallet"); db.commit()
    return jsonify({"message": f"₹{amount} added to your wallet (demo mode)."})


@app.post("/api/wallet/withdraw")
def withdraw():
    user, data = current_user(), request.get_json(silent=True) or {}
    if not user: return jsonify({"error": "Please log in first."}), 401
    try: amount = int(data.get("amount", 0))
    except (TypeError, ValueError): amount = 0
    upi_id = data.get("upi_id", "").strip()
    if not re.fullmatch(r"[\w.\-]{2,256}@[\w.\-]{2,64}", upi_id): return jsonify({"error": "Enter a valid UPI ID."}), 400
    with closing(get_db()) as db:
        fresh = db.execute("SELECT wallet_balance FROM users WHERE id = ?", (user["id"],)).fetchone()
        if amount < 10 or amount > fresh["wallet_balance"]: return jsonify({"error": "Withdraw at least ₹10 and no more than your wallet balance."}), 400
        db.execute("UPDATE users SET wallet_balance = wallet_balance - ?, upi_id = ? WHERE id = ?", (amount, upi_id, user["id"]))
        db.execute("INSERT INTO wallet_transactions (user_id, amount, transaction_type, note) VALUES (?, ?, 'withdrawal', ?)", (user["id"], -amount, f"Demo UPI withdrawal to {upi_id}"))
        add_notification(db, user["id"], f"₹{amount} withdrawal to {upi_id} was recorded (demo mode).", "wallet"); db.commit()
    return jsonify({"message": "Withdrawal recorded. A real deployment must submit this to a payment provider."})


@app.post("/api/requests/<int:request_id>/accept")
def accept_request(request_id: int):
    user = current_user()
    if not user: return jsonify({"error": "Please log in first."}), 401
    with closing(get_db()) as db:
        row = db.execute("SELECT r.*, i.title, i.owner_id, i.exchange_deadline FROM swap_requests r JOIN items i ON i.id=r.item_id WHERE r.id=? AND i.owner_id=?", (request_id, user["id"])).fetchone()
        if not row or row["status"] != "pending": return jsonify({"error": "Pending request not found."}), 404
        if row["exchange_deadline"] and db.execute("SELECT datetime(?) <= datetime('now')", (row["exchange_deadline"],)).fetchone()[0]: return jsonify({"error": "The one-week exchange window has ended."}), 400
        db.execute("UPDATE swap_requests SET status='accepted' WHERE id=?", (request_id,))
        db.execute("UPDATE swap_requests SET status='declined' WHERE item_id=? AND id<>? AND status='pending'", (row["item_id"], request_id))
        db.execute("UPDATE items SET is_available=0 WHERE id=?", (row["item_id"],))
        add_notification(db, row["requester_id"], f"Your request for {row['title']} was accepted. Open chat to arrange pickup.", "accepted", request_id)
        db.commit()
    return jsonify({"message": "Request accepted. The buyer can now pay through the wallet or arrange the swap."})


@app.get("/api/requests/incoming")
def incoming_requests():
    user = current_user()
    if not user: return jsonify({"error": "Please log in first."}), 401
    with closing(get_db()) as db:
        rows = db.execute("""SELECT r.*, i.title, i.listing_type, i.rupees, i.platform_fee FROM swap_requests r
                             JOIN items i ON i.id=r.item_id WHERE i.owner_id=? ORDER BY r.created_at DESC""", (user["id"],)).fetchall()
    return jsonify([dict(x) for x in rows])


def contains_personal_info(text: str) -> bool:
    lowered = text.lower()
    return bool(re.search(r"\d", text)) or any(x in lowered for x in ("@", "instagram", "insta", "snapchat", "snap id", "phone", "whatsapp", "telegram", "email", "gmail"))


@app.get("/api/requests/<int:request_id>/messages")
def get_messages(request_id: int):
    user = current_user()
    if not user: return jsonify({"error": "Please log in first."}), 401
    with closing(get_db()) as db:
        request_row = request_for_member(db, request_id, user["id"])
        if not request_row or request_row["status"] not in ("accepted", "delivered"): return jsonify({"error": "Chat opens after the owner accepts."}), 403
        rows = db.execute("SELECT id, sender_id, body, created_at FROM messages WHERE request_id=? ORDER BY id", (request_id,)).fetchall()
    return jsonify([dict(x) for x in rows])


@app.get("/api/requests/<int:request_id>/messages/stream")
def message_stream(request_id: int):
    # Server-sent events let the open chat receive a prompt refresh without a page reload.
    user = current_user()
    if not user: return jsonify({"error": "Please log in first."}), 401
    return Response("event: ping\ndata: refresh\n\n", mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/requests/<int:request_id>/messages")
def send_message(request_id: int):
    user, body = current_user(), (request.get_json(silent=True) or {}).get("body", "").strip()
    if not user: return jsonify({"error": "Please log in first."}), 401
    if not body or contains_personal_info(body): return jsonify({"error": "For safety, do not send numbers, email addresses, or social-media/contact details."}), 400
    with closing(get_db()) as db:
        row = request_for_member(db, request_id, user["id"])
        if not row or row["status"] != "accepted": return jsonify({"error": "Chat opens after acceptance."}), 403
        db.execute("INSERT INTO messages (request_id, sender_id, body) VALUES (?, ?, ?)", (request_id, user["id"], body))
        other = row["owner_id"] if row["requester_id"] == user["id"] else row["requester_id"]
        add_notification(db, other, f"You have a new anonymous message about {row['title']}.", "message", request_id); db.commit()
    return jsonify({"message": "Message sent."})


@app.post("/api/requests/<int:request_id>/pay")
def pay_for_request(request_id: int):
    buyer = current_user()
    if not buyer: return jsonify({"error": "Please log in first."}), 401
    with closing(get_db()) as db:
        row = request_for_member(db, request_id, buyer["id"])
        if not row or row["requester_id"] != buyer["id"] or row["status"] != "accepted": return jsonify({"error": "Accepted purchase not found."}), 404
        if row["listing_type"] != "sell": return jsonify({"error": "Wallet payment is only needed for rupee listings."}), 400
        if row["payment_status"] in ("held", "released"): return jsonify({"error": "This purchase has already been paid."}), 409
        balance = db.execute("SELECT wallet_balance FROM users WHERE id=?", (buyer["id"],)).fetchone()["wallet_balance"]
        if balance < row["rupees"]: return jsonify({"error": f"Insufficient wallet balance. Add ₹{row['rupees'] - balance} first."}), 400
        db.execute("UPDATE users SET wallet_balance = wallet_balance - ? WHERE id=?", (row["rupees"], buyer["id"]))
        db.execute("UPDATE swap_requests SET payment_status='held' WHERE id=?", (request_id,))
        db.execute("INSERT INTO wallet_transactions (user_id, amount, transaction_type, note, request_id) VALUES (?, ?, 'escrow_hold', ?, ?)", (buyer["id"], -row["rupees"], f"Funds held for {row['title']} until delivery confirmation", request_id))
        add_notification(db, buyer["id"], f"₹{row['rupees']} is safely held for {row['title']}. Confirm delivery to release payment.", "payment", request_id)
        add_notification(db, row["owner_id"], f"Payment for {row['title']} is held securely. It will be released after the buyer confirms delivery.", "payment", request_id)
        db.commit()
    return jsonify({"message": "Payment is held securely. It will be released to the seller after you confirm delivery."})


@app.post("/api/requests/<int:request_id>/complete")
def complete_request(request_id: int):
    user = current_user()
    if not user: return jsonify({"error": "Please log in first."}), 401
    with closing(get_db()) as db:
        row = request_for_member(db, request_id, user["id"])
        if not row or row["requester_id"] != user["id"] or row["status"] != "accepted": return jsonify({"error": "Accepted request not found."}), 404
        if row["listing_type"] == "sell" and row["payment_status"] != "held": return jsonify({"error": "Pay through your EcoCredit wallet before marking this purchase delivered."}), 400
        db.execute("UPDATE swap_requests SET status='delivered' WHERE id=?", (request_id,))
        if row["listing_type"] == "sell":
            seller_amount = row["rupees"] - row["platform_fee"]
            db.execute("UPDATE users SET wallet_balance = wallet_balance + ? WHERE id=?", (seller_amount, row["owner_id"]))
            db.execute("UPDATE swap_requests SET payment_status='released' WHERE id=?", (request_id,))
            db.execute("INSERT INTO wallet_transactions (user_id, amount, transaction_type, note, request_id) VALUES (?, ?, 'sale_release', ?, ?)", (row["owner_id"], seller_amount, f"Escrow released for {row['title']} after ₹{row['platform_fee']} platform fee", request_id))
            add_notification(db, row["owner_id"], f"₹{seller_amount} for {row['title']} was released to your wallet after the 5% platform fee.", "payment", request_id)
        add_notification(db, row["owner_id"], f"{row['title']} was marked delivered. The buyer can now rate the exchange.", "delivered", request_id); db.commit()
    return jsonify({"message": "Marked as delivered. The held payment has been released to the seller wallet after the 5% fee." if row["listing_type"] == "sell" else "Marked as delivered. You can now rate the exchange."})


@app.post("/api/users/<int:user_id>/rating")
def rate_user(user_id: int):
    rater, data = current_user(), request.get_json(silent=True) or {}
    try: score, request_id = int(data.get("score", 0)), int(data.get("request_id", 0))
    except (TypeError, ValueError): score, request_id = 0, 0
    if not rater: return jsonify({"error": "Please log in first."}), 401
    if score not in range(1, 6): return jsonify({"error": "Rating must be from 1 to 5."}), 400
    with closing(get_db()) as db:
        eligible = db.execute("""SELECT i.title FROM swap_requests r JOIN items i ON i.id=r.item_id
                               WHERE r.id=? AND r.requester_id=? AND i.owner_id=? AND r.status='delivered'""", (request_id, rater["id"], user_id)).fetchone()
        if not eligible: return jsonify({"error": "You can rate only after your delivered exchange."}), 403
        if db.execute("SELECT 1 FROM ratings WHERE request_id=? AND rater_id=?", (request_id, rater["id"])).fetchone(): return jsonify({"error": "You have already rated this exchange."}), 409
        db.execute("UPDATE users SET rating_total=rating_total+?, rating_count=rating_count+1 WHERE id=?", (score, user_id))
        db.execute("INSERT INTO ratings (request_id, rater_id, score) VALUES (?, ?, ?)", (request_id, rater["id"], score))
        add_notification(db, user_id, f"You received a {score}/5 rating for {eligible['title']}.", "rating", request_id); db.commit()
    return jsonify({"message": "Thank you for rating the exchange."})


@app.get("/api/notifications")
def notifications():
    user = current_user()
    if not user: return jsonify({"error": "Please log in first."}), 401
    with closing(get_db()) as db:
        rows = db.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 30", (user["id"],)).fetchall()
    return jsonify([dict(row) for row in rows])


@app.post("/api/notifications/read")
def read_notifications():
    user = current_user()
    if not user: return jsonify({"error": "Please log in first."}), 401
    with closing(get_db()) as db:
        db.execute("UPDATE notifications SET read_at=CURRENT_TIMESTAMP WHERE user_id=? AND read_at IS NULL", (user["id"],)); db.commit()
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True)
