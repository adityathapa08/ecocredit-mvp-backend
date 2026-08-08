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
        """)
        # Safe migrations for an existing hackathon database.
        columns = {row[1] for row in db.execute("PRAGMA table_info(items)").fetchall()}
        if "listing_type" not in columns:
            db.execute("ALTER TABLE items ADD COLUMN listing_type TEXT NOT NULL DEFAULT 'swap'")
        if "rupees" not in columns:
            db.execute("ALTER TABLE items ADD COLUMN rupees INTEGER")
        if "image_data" not in columns:
            db.execute("ALTER TABLE items ADD COLUMN image_data TEXT DEFAULT ''")
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
    query = "SELECT * FROM items WHERE is_available = 1"
    values: list[str] = []
    if category != "All":
        query += " AND category = ?"
        values.append(category)
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


@app.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    name = data.get("name", "").strip() or email.split("@")[0].replace(".", " ").title()
    if "@" not in email or len(password) < 4:
        return jsonify({"error": "Use a valid college email and a password of at least 4 characters."}), 400
    with closing(get_db()) as db:
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not user:
            cursor = db.execute("INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                                (name, email, generate_password_hash(password)))
            user = db.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
            db.commit()
        elif not check_password_hash(user["password_hash"], password):
            return jsonify({"error": "Incorrect password for this email."}), 401
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
    required = ("title", "category", "condition", "location", "listing_type")
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
        db.execute("""INSERT INTO items (title, category, item_condition, location, points, emoji, description, owner_name, listing_type, rupees, image_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                   (data["title"].strip(), data["category"], data["condition"].strip(), data["location"].strip(),
                    int(data.get("points") or 0), data.get("emoji", "♻️"), data.get("description", "A useful campus item."), user["name"],
                    listing_type, int(data.get("rupees") or 0) if listing_type == "sell" else None, image_data))
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


if __name__ == "__main__":
    app.run(debug=True)
