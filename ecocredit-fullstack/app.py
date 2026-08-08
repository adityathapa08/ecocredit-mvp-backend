from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path

from flask import Flask, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "ecocredit.db"

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


def seed_database() -> None:
    with closing(get_db()) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                hostel TEXT NOT NULL DEFAULT 'Hostel A',
                eco_points INTEGER NOT NULL DEFAULT 120
                ,rating_total INTEGER NOT NULL DEFAULT 0
                ,rating_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                category TEXT NOT NULL,
                item_condition TEXT NOT NULL,
                location TEXT NOT NULL,
                points INTEGER NOT NULL,
                emoji TEXT NOT NULL,
                description TEXT NOT NULL,
                owner_name TEXT NOT NULL,
                is_available INTEGER NOT NULL DEFAULT 1,
                listing_type TEXT NOT NULL DEFAULT 'swap',
                rupees INTEGER,
                image_data TEXT DEFAULT ''
                ,actual_price INTEGER
                ,exchange_deadline TEXT
                ,owner_id INTEGER
                ,platform_fee INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS swap_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id INTEGER NOT NULL,
                requester_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(item_id) REFERENCES items(id),
                FOREIGN KEY(requester_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER NOT NULL,
                sender_id INTEGER NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER NOT NULL,
                rater_id INTEGER NOT NULL,
                score INTEGER NOT NULL,
                UNIQUE(request_id, rater_id)
            );
        """)
        # Safe migrations for an existing hackathon database.
        columns = {row[1] for row in db.execute("PRAGMA table_info(items)").fetchall()}
        if "listing_type" not in columns:
            db.execute("ALTER TABLE items ADD COLUMN listing_type TEXT NOT NULL DEFAULT 'swap'")
        if "rupees" not in columns:
            db.execute("ALTER TABLE items ADD COLUMN rupees INTEGER")
        if "image_data" not in columns:
            db.execute("ALTER TABLE items ADD COLUMN image_data TEXT DEFAULT ''")
        if "actual_price" not in columns:
            db.execute("ALTER TABLE items ADD COLUMN actual_price INTEGER")
        if "exchange_deadline" not in columns:
            db.execute("ALTER TABLE items ADD COLUMN exchange_deadline TEXT")
        if "owner_id" not in columns:
            db.execute("ALTER TABLE items ADD COLUMN owner_id INTEGER")
        if "platform_fee" not in columns:
            db.execute("ALTER TABLE items ADD COLUMN platform_fee INTEGER NOT NULL DEFAULT 0")
        if db.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0:
            items = [
                ("First-year CSE books", "Study", "Like new", "Library Block", 120, "📚", "Programming, maths and engineering basics.", "Riya S."),
                ("Hostel essentials kit", "Hostel", "Good", "Hostel C", 40, "🪣", "Bucket, mug and clothes hangers.", "Karan M."),
                ("Wired headphones", "Tech", "Excellent", "Campus Cafe", 55, "🎧", "Working perfectly. 3.5 mm jack.", "Aman J."),
                ("Winter jacket", "Clothing", "Like new", "Hostel B", 90, "🧥", "Size M. Worn for one semester.", "Priya D."),
                ("Scientific calculator", "Study", "Good", "Academic Block", 70, "🧮", "Perfect for first-year maths and physics.", "Dev R."),
                ("Desk lamp", "Hostel", "Excellent", "Hostel A", 45, "💡", "Warm light LED desk lamp.", "Nisha K."),
            ]
            db.executemany("""INSERT INTO items
                (title, category, item_condition, location, points, emoji, description, owner_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", items)
        db.commit()


# Run this when Flask is imported by Gunicorn as well as when app.py is run locally.
seed_database()


@app.get("/")
def home():
    return render_template("index.html")


@app.get("/api/items")
def list_items():
    category = request.args.get("category", "All")
    search = request.args.get("search", "").strip()
    query = "SELECT * FROM items WHERE is_available = 1"
    values: list[str] = []
    if category != "All":
        query += " AND category = ?"
        values.append(category)
    if search:
        query += " AND (title LIKE ? OR description LIKE ? OR category LIKE ?)"
        values.extend([f"%{search}%"] * 3)
    query += " ORDER BY id DESC"
    with closing(get_db()) as db:
        rows = db.execute(query, values).fetchall()
    return jsonify([dict(row) for row in rows])


@app.get("/api/me")
def me():
    user = current_user()
    if not user:
        return jsonify({"logged_in": False})
    return jsonify({"logged_in": True, "user": dict(user)})


@app.post("/api/auth/signup")
def signup():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    name = data.get("name", "").strip()
    hostel = data.get("hostel", "").strip()
    if not name or not hostel or "@" not in email or len(password) < 4:
        return jsonify({"error": "Enter your name, campus area, valid college email, and a 4-character password."}), 400
    with closing(get_db()) as db:
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user:
            return jsonify({"error": "An account already exists for this email. Please log in."}), 409
        cursor = db.execute("INSERT INTO users (name, email, password_hash, hostel) VALUES (?, ?, ?, ?)",
                            (name, email, generate_password_hash(password), hostel))
        user = db.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
        db.commit()
        session["user_id"] = user["id"]
    return jsonify({"user": dict(user)})


@app.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    email, password = data.get("email", "").strip().lower(), data.get("password", "")
    with closing(get_db()) as db:
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Incorrect email or password."}), 401
    session["user_id"] = user["id"]
    return jsonify({"user": dict(user)})


@app.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.post("/api/items")
def create_item():
    user = current_user()
    if not user:
        return jsonify({"error": "Please log in first."}), 401
    data = request.get_json(silent=True) or {}
    required = ("title", "category", "condition", "location", "listing_type", "actual_price")
    if any(not str(data.get(field, "")).strip() for field in required):
        return jsonify({"error": "Please complete all item details."}), 400
    listing_type = data["listing_type"]
    if listing_type not in ("swap", "sell"):
        return jsonify({"error": "Choose Swap for Eco Points or Sell for Rupees."}), 400
    if listing_type == "swap" and int(data.get("points") or 0) < 1:
        return jsonify({"error": "Enter the Eco Points needed for this swap."}), 400
    if listing_type == "sell" and int(data.get("rupees") or 0) < 1:
        return jsonify({"error": "Enter a rupee price for this item."}), 400
    image_data = data.get("image_data", "")
    if image_data and not image_data.startswith("data:image/"):
        return jsonify({"error": "Please upload an image file."}), 400
    with closing(get_db()) as db:
        db.execute("""INSERT INTO items (title, category, item_condition, location, points, emoji, description, owner_name, listing_type, rupees, image_data, actual_price, exchange_deadline)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', '+7 days'))""",
                   (data["title"].strip(), data["category"], data["condition"].strip(), data["location"].strip(),
                    int(data.get("points") or 0), data.get("emoji", "♻️"), data.get("description", "A useful campus item."), user["name"],
                    listing_type, int(data.get("rupees") or 0) if listing_type == "sell" else None, image_data, int(data["actual_price"])))
        item_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        fee = round(int(data.get("rupees") or 0) * .05) if listing_type == "sell" else 0
        db.execute("UPDATE items SET owner_id = ?, platform_fee = ? WHERE id = ?", (user["id"], fee, item_id))
        db.execute("UPDATE users SET eco_points = eco_points + 10 WHERE id = ?", (user["id"],))
        db.commit()
    return jsonify({"message": "Item listed! You earned 10 Eco Points."}), 201


@app.post("/api/items/<int:item_id>/request")
def request_swap(item_id: int):
    user = current_user()
    if not user:
        return jsonify({"error": "Please log in first."}), 401
    with closing(get_db()) as db:
        item = db.execute("SELECT id FROM items WHERE id = ? AND is_available = 1", (item_id,)).fetchone()
        if not item:
            return jsonify({"error": "This item is no longer available."}), 404
        exists = db.execute("SELECT id FROM swap_requests WHERE item_id = ? AND requester_id = ?", (item_id, user["id"])).fetchone()
        if exists:
            return jsonify({"error": "You have already requested this item."}), 409
        db.execute("INSERT INTO swap_requests (item_id, requester_id) VALUES (?, ?)", (item_id, user["id"]))
        db.commit()
    return jsonify({"message": "Request sent! The pickup location is shared only after both students agree. Pay on delivery applies to rupee listings."}), 201


@app.get("/api/stats")
def stats():
    with closing(get_db()) as db:
        item_count = db.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        request_count = db.execute("SELECT COUNT(*) FROM swap_requests").fetchone()[0]
    return jsonify({"waste_prevented": 286 + item_count * 2, "items_reused": 1248 + item_count, "student_savings": "₹ 1.8L", "requests": request_count})


@app.get("/api/profile")
def profile():
    user = current_user()
    if not user:
        return jsonify({"error": "Please log in first."}), 401
    with closing(get_db()) as db:
        listings = db.execute("SELECT * FROM items WHERE owner_id = ? OR (owner_id IS NULL AND owner_name = ?) ORDER BY id DESC", (user["id"], user["name"])).fetchall()
        requests = db.execute("""SELECT r.*, i.title, i.listing_type, i.rupees, i.points, i.owner_id
                              FROM swap_requests r JOIN items i ON i.id = r.item_id
                              WHERE r.requester_id = ? ORDER BY r.created_at DESC""", (user["id"],)).fetchall()
    rating = round(user["rating_total"] / user["rating_count"], 1) if user["rating_count"] else None
    return jsonify({"user": {**dict(user), "rating": rating}, "listings": [dict(x) for x in listings], "requests": [dict(x) for x in requests]})


@app.put("/api/profile")
def update_profile():
    user = current_user()
    data = request.get_json(silent=True) or {}
    name, hostel = data.get("name", "").strip(), data.get("hostel", "").strip()
    if not user or not name or not hostel:
        return jsonify({"error": "Name and campus area are required."}), 400
    with closing(get_db()) as db:
        db.execute("UPDATE users SET name = ?, hostel = ? WHERE id = ?", (name, hostel, user["id"]))
        db.execute("UPDATE items SET owner_name = ? WHERE owner_id = ?", (name, user["id"]))
        db.commit()
    return jsonify({"message": "Profile updated."})


@app.post("/api/requests/<int:request_id>/accept")
def accept_request(request_id: int):
    user = current_user()
    if not user: return jsonify({"error": "Please log in first."}), 401
    with closing(get_db()) as db:
        row = db.execute("SELECT r.item_id FROM swap_requests r JOIN items i ON i.id=r.item_id WHERE r.id=? AND i.owner_id=?", (request_id, user["id"])).fetchone()
        if not row: return jsonify({"error": "Request not found."}), 404
        db.execute("UPDATE swap_requests SET status='accepted' WHERE id=?", (request_id,))
        db.execute("UPDATE items SET is_available=0 WHERE id=?", (row["item_id"],))
        db.commit()
    return jsonify({"message": "Request accepted. Chat is now open; arrange a safe campus pickup."})


@app.get("/api/requests/incoming")
def incoming_requests():
    user = current_user()
    if not user: return jsonify({"error": "Please log in first."}), 401
    with closing(get_db()) as db:
        rows = db.execute("SELECT r.*, i.title FROM swap_requests r JOIN items i ON i.id=r.item_id WHERE i.owner_id=? ORDER BY r.created_at DESC", (user["id"],)).fetchall()
    return jsonify([dict(x) for x in rows])


def contains_personal_info(text: str) -> bool:
    lowered = text.lower()
    return any(x in lowered for x in ("@", "instagram", "insta", "snapchat", "snap id", "phone", "whatsapp", "telegram")) or any(c.isdigit() for c in text)


@app.get("/api/requests/<int:request_id>/messages")
def get_messages(request_id: int):
    user = current_user()
    if not user: return jsonify({"error": "Please log in first."}), 401
    with closing(get_db()) as db:
        permitted = db.execute("SELECT 1 FROM swap_requests r JOIN items i ON i.id=r.item_id WHERE r.id=? AND (r.requester_id=? OR i.owner_id=?) AND r.status IN ('accepted','delivered')", (request_id,user["id"],user["id"])).fetchone()
        if not permitted: return jsonify({"error": "Chat opens after the owner accepts."}), 403
        rows=db.execute("SELECT sender_id, body, created_at FROM messages WHERE request_id=? ORDER BY id",(request_id,)).fetchall()
    return jsonify([dict(x) for x in rows])


@app.post("/api/requests/<int:request_id>/messages")
def send_message(request_id: int):
    user = current_user(); body=(request.get_json(silent=True) or {}).get("body", "").strip()
    if not user: return jsonify({"error": "Please log in first."}), 401
    if not body or contains_personal_info(body): return jsonify({"error": "For safety, do not send numbers, email addresses, or social-media/contact details."}), 400
    with closing(get_db()) as db:
        permitted=db.execute("SELECT 1 FROM swap_requests r JOIN items i ON i.id=r.item_id WHERE r.id=? AND (r.requester_id=? OR i.owner_id=?) AND r.status='accepted'",(request_id,user["id"],user["id"])).fetchone()
        if not permitted:return jsonify({"error":"Chat opens after acceptance."}),403
        db.execute("INSERT INTO messages (request_id,sender_id,body) VALUES (?,?,?)",(request_id,user["id"],body)); db.commit()
    return jsonify({"message":"Message sent."})


@app.post("/api/requests/<int:request_id>/complete")
def complete_request(request_id: int):
    """MVP delivery status: a completed handover becomes delivered after the agreed pickup."""
    user = current_user()
    if not user:
        return jsonify({"error": "Please log in first."}), 401
    with closing(get_db()) as db:
        result = db.execute("UPDATE swap_requests SET status = 'delivered' WHERE id = ? AND requester_id = ?", (request_id, user["id"]))
        db.commit()
    if not result.rowcount:
        return jsonify({"error": "Request not found."}), 404
    return jsonify({"message": "Marked as delivered. You can now rate the exchange."})


@app.post("/api/users/<int:user_id>/rating")
def rate_user(user_id: int):
    rater = current_user()
    data = request.get_json(silent=True) or {}
    score, request_id = int(data.get("score", 0)), int(data.get("request_id", 0))
    if not rater:
        return jsonify({"error": "Please log in first."}), 401
    if score not in range(1, 6):
        return jsonify({"error": "Rating must be from 1 to 5."}), 400
    with closing(get_db()) as db:
        eligible = db.execute("""SELECT 1 FROM swap_requests r JOIN items i ON i.id=r.item_id
                               WHERE r.id=? AND r.requester_id=? AND i.owner_id=? AND r.status='delivered'""",
                              (request_id, rater["id"], user_id)).fetchone()
        if not eligible:
            return jsonify({"error": "You can rate only after your delivered exchange."}), 403
        if db.execute("SELECT 1 FROM ratings WHERE request_id=? AND rater_id=?", (request_id, rater["id"])).fetchone():
            return jsonify({"error": "You have already rated this exchange."}), 409
        db.execute("UPDATE users SET rating_total = rating_total + ?, rating_count = rating_count + 1 WHERE id = ?", (score, user_id))
        db.execute("INSERT INTO ratings (request_id, rater_id, score) VALUES (?, ?, ?)", (request_id, rater["id"], score))
        db.commit()
    return jsonify({"message": "Thank you for rating the exchange."})


if __name__ == "__main__":
    app.run(debug=True)
