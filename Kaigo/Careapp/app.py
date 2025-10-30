# app.py  ― デジタル介護日誌（完全版／Flask-Babel v3対応）

from flask import (
    Flask, render_template, request, redirect, send_file,
    session, url_for, flash, g
)
from functools import wraps
from flask_babel import Babel, gettext as _
import sqlite3
import qrcode
import io
import secrets
import os
from datetime import date

# =========================
# 基本設定
# =========================
app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

DB_PATH = "care.db"

# ---- 多言語設定（Flask-Babel v3+）----
app.config["BABEL_DEFAULT_LOCALE"] = "ja"
app.config["BABEL_TRANSLATION_DIRECTORIES"] = "translations"
LANGUAGES = ["ja", "en"]

def select_locale():
    # セッションに保存した指定言語があればそれを使う（なければ日本語）
    return session.get("lang", "ja")

babel = Babel(app, locale_selector=select_locale)

# Jinja に共通で渡す（現在言語・利用可能言語）
@app.context_processor
def inject_globals():
    return {
        "current_lang": select_locale(),
        "LANGUAGES": LANGUAGES
    }

# =========================
# DBユーティリティ
# =========================
def get_connection():
    return sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)

def column_exists(cursor, table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cursor.fetchall()]
    return column in cols

def table_exists(cursor, table):
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,)
    )
    return cursor.fetchone() is not None

def init_db():
    with get_connection() as conn:
        c = conn.cursor()

        # --- users ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS users(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT,
              age INTEGER,
              gender TEXT,
              room_number TEXT,
              notes TEXT
            )
        """)
        # カラム補修（古いDBでも動くように）
        if not column_exists(c, "users", "room_number"):
            c.execute("ALTER TABLE users ADD COLUMN room_number TEXT")
        if not column_exists(c, "users", "notes"):
            c.execute("ALTER TABLE users ADD COLUMN notes TEXT")

        # --- records ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS records(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER,
              meal TEXT,
              medication TEXT,
              toilet TEXT,
              condition TEXT,
              memo TEXT,
              staff_name TEXT,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        if not column_exists(c, "records", "staff_name"):
            c.execute("ALTER TABLE records ADD COLUMN staff_name TEXT")

        # --- staff ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS staff(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT UNIQUE,
              password TEXT,
              role TEXT,
              login_token TEXT
            )
        """)

        # --- handover ---
        c.execute("""
            CREATE TABLE IF NOT EXISTS handover(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              on_date TEXT,
              shift TEXT,
              resident_id INTEGER,
              priority INTEGER,
              title TEXT,
              body TEXT,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()

# 初回起動 or 既存DB補修
init_db()

# =========================
# 認証デコレータ
# =========================
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "staff_name" not in session:
            flash(_("ログインが必要です。"))
            return redirect(url_for("staff_login"))
        return f(*args, **kwargs)
    return wrapper

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("staff_role") != "admin":
            return _("❌ 管理者権限が必要です。"), 403
        return f(*args, **kwargs)
    return wrapper

# =========================
# 言語切替
# =========================
@app.route("/set_language/<lang>")
def set_language(lang):
    if lang in LANGUAGES:
        session["lang"] = lang
        flash(_("言語を切り替えました: ") + lang)
    return redirect(request.referrer or url_for("home"))

# =========================
# ルート：ホーム
# =========================
@app.route("/")
def home():
    staff_name = session.get("staff_name")
    staff_role = session.get("staff_role")
    return render_template("home.html",
                           staff_name=staff_name,
                           staff_role=staff_role)

# =========================
# スタッフ登録/ログイン/ログアウト
# =========================
@app.route("/staff_register", methods=["GET", "POST"])
def staff_register():
    if request.method == "POST":
        name = request.form.get("name")
        password = request.form.get("password")
        role = "caregiver"
        if not name or not password:
            flash(_("名前とパスワードを入力してください。"))
            return render_template("staff_register.html")
        try:
            with get_connection() as conn:
                c = conn.cursor()
                c.execute(
                    "INSERT INTO staff (name, password, role) VALUES (?, ?, ?)",
                    (name, password, role)
                )
                conn.commit()
            flash(_("登録が完了しました。ログインしてください。"))
            return redirect(url_for("staff_login"))
        except sqlite3.IntegrityError:
            flash(_("同じ名前のスタッフが既に存在します。"))
    return render_template("staff_register.html")

@app.route("/staff_login", methods=["GET", "POST"])
def staff_login():
    if request.method == "POST":
        name = request.form.get("name")
        password = request.form.get("password")
        with get_connection() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT name, role FROM staff WHERE name=? AND password=?",
                (name, password)
            )
            staff = c.fetchone()
        if staff:
            session["staff_name"] = staff[0]
            session["staff_role"] = staff[1]
            flash(_("%s さんでログインしました。") % staff[0])
            return redirect(url_for("home"))
        else:
            flash(_("名前またはパスワードが間違っています。"))
    return render_template("staff_login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash(_("ログアウトしました。"))
    return redirect(url_for("home"))

# =========================
# 利用者：一覧・追加・削除（管理者）
# =========================
@app.route("/users")
@admin_required
def users_page():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id, name, age, gender, room_number, notes FROM users ORDER BY id"
        )
        users = c.fetchall()
    return render_template("users.html", users=users)

@app.route("/add_user", methods=["GET", "POST"])
@admin_required
def add_user():
    if request.method == "POST":
        name = request.form.get("name")
        age = request.form.get("age")
        gender = request.form.get("gender")
        room_number = request.form.get("room_number")
        notes = request.form.get("notes")
        with get_connection() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO users (name, age, gender, room_number, notes) VALUES (?, ?, ?, ?, ?)",
                (name, age, gender, room_number, notes)
            )
            conn.commit()
        flash(_("利用者を登録しました。"))
        return redirect(url_for("users_page"))
    return render_template("add_user.html")

@app.route("/delete_user/<int:user_id>")
@admin_required
def delete_user(user_id):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
    flash(_("利用者を削除しました。"))
    return redirect(url_for("users_page"))

# =========================
# 記録：一覧
# =========================
@app.route("/records")
@login_required
def records():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT r.id, u.name, r.meal, r.medication, r.toilet, r.condition,
                   r.memo, r.staff_name, r.created_at
            FROM records r
            JOIN users u ON r.user_id = u.id
            ORDER BY r.id DESC
        """)
        rows = c.fetchall()
    return render_template("records.html", rows=rows)

# =========================
# 記録：追加（選択式）
# =========================
@app.route("/add_record", methods=["GET", "POST"])
@login_required
def add_record():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name FROM users ORDER BY id")
        users = c.fetchall()

    MEAL_CHOICES = ["全量", "8割", "半分", "1/3", "ほぼ食べず", "その他"]
    MEDICATION_CHOICES = ["済", "一部", "未", "自己管理", "その他"]
    TOILET_CHOICES = ["自立", "誘導", "介助", "失禁なし", "失禁あり", "その他"]
    CONDITION_CHOICES = ["良好", "普通", "要観察", "受診", "発熱(37.5℃～)", "その他"]

    if request.method == "POST":
        def picked(val, other):
            other = (other or "").strip()
            return other if (val == "その他" and other) else val

        user_id = request.form.get("user_id")
        meal = picked(request.form.get("meal"), request.form.get("meal_other"))
        medication = picked(request.form.get("medication"), request.form.get("medication_other"))
        toilet = picked(request.form.get("toilet"), request.form.get("toilet_other"))
        condition = picked(request.form.get("condition"), request.form.get("condition_other"))
        memo = request.form.get("memo")
        staff_name = session.get("staff_name")

        with get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO records (user_id, meal, medication, toilet, condition, memo, staff_name)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, meal, medication, toilet, condition, memo, staff_name))
            conn.commit()

        flash(_("記録を保存しました。"))
        return redirect(url_for("records"))

    return render_template("add_record.html",
                           users=users,
                           MEAL_CHOICES=MEAL_CHOICES,
                           MEDICATION_CHOICES=MEDICATION_CHOICES,
                           TOILET_CHOICES=TOILET_CHOICES,
                           CONDITION_CHOICES=CONDITION_CHOICES)

# =========================
# 引継ぎボード
# =========================
@app.route("/handover", methods=["GET", "POST"])
@login_required
def handover():
    on_date = request.args.get("date") or date.today().isoformat()
    shift = request.args.get("shift") or "day"
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name FROM users ORDER BY id")
        residents = c.fetchall()
        c.execute("""
            SELECT h.id, h.on_date, h.shift, u.name, h.priority, h.title, h.body, h.created_at
            FROM handover h
            LEFT JOIN users u ON h.resident_id = u.id
            WHERE h.on_date = ? AND h.shift = ?
            ORDER BY h.priority ASC, h.id DESC
        """, (on_date, shift))
        items = c.fetchall()
    return render_template("handover.html",
                           items=items, residents=residents,
                           on_date=on_date, shift=shift)

@app.route("/handover/add", methods=["POST"])
@login_required
def handover_add():
    on_date = request.form.get("on_date") or date.today().isoformat()
    shift = request.form.get("shift") or "day"
    resident_id = request.form.get("resident_id")
    priority = request.form.get("priority") or 2
    title = request.form.get("title")
    body = request.form.get("body")
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO handover(on_date, shift, resident_id, priority, title, body)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (on_date, shift, resident_id, priority, title, body))
        conn.commit()
    flash(_("引継ぎを追加しました。"))
    return redirect(url_for("handover", date=on_date, shift=shift))

# =========================
# 管理ページ
# =========================
@app.route("/admin")
@admin_required
def admin_page():
    staff_name = session.get("staff_name")
    return render_template("admin.html", staff_name=staff_name)

# =========================
# スタッフ管理（一覧/削除/QR）
# =========================
@app.route("/staff_list")
@admin_required
def staff_list():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, password, role, login_token FROM staff ORDER BY id")
        staff = c.fetchall()
    return render_template("staff_list.html", staff_list=staff)

@app.route("/delete_staff/<int:sid>")
@admin_required
def delete_staff(sid):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM staff WHERE id=?", (sid,))
        conn.commit()
    flash(_("スタッフを削除しました。"))
    return redirect(url_for("staff_list"))

@app.route("/qr/<name>")
@admin_required
def qr_reissue(name):
    token = secrets.token_hex(8)
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE staff SET login_token=? WHERE name=?", (token, name))
        conn.commit()
    flash(_("QR を再発行しました。"))
    return redirect(url_for("staff_list"))

@app.route("/generate_qr", methods=["GET", "POST"])
@admin_required
def generate_qr():
    if request.method == "POST":
        name = request.form.get("name")
        role = request.form.get("role") or "caregiver"
        token = secrets.token_hex(8)
        with get_connection() as conn:
            c = conn.cursor()
            # name が無ければ新規、あればトークンを上書き
            c.execute("""
                INSERT INTO staff (name, role, login_token)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET role=excluded.role, login_token=excluded.login_token
            """, (name, role, token))
            conn.commit()

        host = request.host.split(":")[0]
        login_url = f"http://{host}:5000/login/{token}"
        img = qrcode.make(login_url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return send_file(buf, mimetype="image/png")
    return render_template("generate_qr.html")

@app.route("/login/<token>")
def login_by_qr(token):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT name, role FROM staff WHERE login_token=?", (token,))
        staff = c.fetchone()
    if staff:
        session["staff_name"] = staff[0]
        session["staff_role"] = staff[1]
        flash(_("%s さんでログインしました。") % staff[0])
        return redirect(url_for("home"))
    return _("無効なQRコードです。"), 403

# =========================
# メイン
# =========================
if __name__ == "__main__":
    # 127.0.0.1 でも 0.0.0.0 でもアクセスできるように
    app.run(host="0.0.0.0", port=5000, debug=True)
