from __future__ import annotations
from flask import (
    Flask, render_template, request, redirect, send_file, send_from_directory,
    session, url_for, flash, jsonify
)
from functools import wraps
import sqlite3, qrcode, io, secrets, os, json, csv, math
from datetime import date, datetime, timedelta

# ===============================
# 基本設定
# ===============================
APP_ROOT = os.path.dirname(__file__)
DB_PATH = os.environ.get("DB_PATH") or os.path.join(APP_ROOT, "care.db")
APP_SECRET = os.environ.get("APP_SECRET") or os.urandom(16)

app = Flask(__name__)
app.secret_key = APP_SECRET

# 🌐 多言語対応のためのダミー関数を追加
def get_locale():
    # Google翻訳で多言語化するため固定でOK
    return "ja"

def _(s, **kwargs):
    try:
        return s % kwargs if kwargs else s
    except Exception:
        return s

# Jinjaで使えるよう登録
app.jinja_env.globals.update(get_locale=get_locale, _=_)

# セッション維持
@app.before_request
def _make_session_permanent():
    session.permanent = True
    app.permanent_session_lifetime = timedelta(days=30)

@app.context_processor
def inject_now():
    return {"now": datetime.now}

# ===============================
# DB 設定
# ===============================
def dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}

def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = dict_factory
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def init_db():
    with get_connection() as conn:
        c = conn.cursor()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            age INTEGER,
            gender TEXT,
            room_number TEXT,
            notes TEXT
        );
        CREATE TABLE IF NOT EXISTS staff(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            login_token TEXT
        );
        CREATE TABLE IF NOT EXISTS records(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            meal TEXT,
            medication TEXT,
            toilet TEXT,
            condition TEXT,
            memo TEXT,
            staff_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS handover(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            h_date TEXT NOT NULL,
            shift TEXT NOT NULL,
            note TEXT NOT NULL,
            staff TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS family(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'family'
        );
        CREATE TABLE IF NOT EXISTS family_map(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            family_name TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            UNIQUE(family_name, user_id)
        );
        """)
        conn.commit()

    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) AS cnt FROM staff WHERE role='admin'")
        if (c.fetchone()["cnt"] or 0) == 0:
            c.execute("INSERT INTO staff(name,password,role) VALUES(?,?,?)",
                      ("admin", "admin", "admin"))
            conn.commit()

init_db()

# ===============================
# ログイン制御
# ===============================
def login_required(f):
    @wraps(f)
    def w(*a, **kw):
        if "staff_name" not in session:
            flash("ログインが必要です。")
            return redirect(url_for("staff_login"))
        return f(*a, **kw)
    return w

def admin_required(f):
    @wraps(f)
    def w(*a, **kw):
        if session.get("staff_role") != "admin":
            return "管理者権限が必要です。", 403
        return f(*a, **kw)
    return w

def family_login_required(f):
    @wraps(f)
    def w(*a, **kw):
        if session.get("family_name") is None:
            flash("家族ログインが必要です。")
            return redirect(url_for("family_login"))
        return f(*a, **kw)
    return w

# ===============================
# ホーム
# ===============================
@app.get("/")
def home():
    return render_template("home.html")

# ===============================
# スタッフ関連
# ===============================
@app.route("/staff_login", methods=["GET","POST"])
def staff_login():
    if request.method == "POST":
        name = request.form.get("name")
        password = request.form.get("password")
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT name, role FROM staff WHERE name=? AND password=?", (name, password))
            row = c.fetchone()
        if row:
            session.clear()
            session["staff_name"], session["staff_role"] = row["name"], row["role"]
            flash(f"{row['name']} さんでログインしました。")
            return redirect(url_for("home"))
        flash("名前またはパスワードが違います。")
    return render_template("staff_login.html")

@app.get("/logout")
def logout():
    session.clear()
    flash("ログアウトしました。")
    return redirect(url_for("home"))

# ===============================
# 管理者画面
# ===============================
@app.get("/admin")
@admin_required
def admin_page():
    return render_template("admin.html")

# ===============================
# 家族ログイン
# ===============================
@app.route("/family_login", methods=["GET","POST"])
def family_login():
    if request.method == "POST":
        name = request.form.get("name")
        password = request.form.get("password")
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT name FROM family WHERE name=? AND password=?", (name, password))
            row = c.fetchone()
        if row:
            session.clear()
            session["family_name"] = row["name"]
            flash(f"{row['name']} さんで家族ログインしました。")
            return redirect(url_for("family_home"))
        flash("名前またはパスワードが間違っています。")
    return render_template("family_login.html")

@app.get("/family_logout")
def family_logout():
    session.pop("family_name", None)
    flash("家族ログアウトしました。")
    return redirect(url_for("home"))

@app.get("/family")
@family_login_required
def family_home():
    fam = session["family_name"]
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
          SELECT u.id, u.name, u.room_number
            FROM users u
            JOIN family_map m ON m.user_id = u.id
           WHERE m.family_name = ?
        """, (fam,))
        users = c.fetchall()
    return render_template("family_home.html", users=users)

# ===============================
# 見守りカメラ（管理者限定）
# ===============================
@app.get("/camera")
@admin_required
def camera_page():
    return render_template("camera.html")

# ===============================
# 健康チェック
# ===============================
@app.get("/healthz")
def healthz():
    return {"ok": True, "time": datetime.now().isoformat()}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
