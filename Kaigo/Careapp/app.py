from flask import (
    Flask, render_template, request, redirect, send_file,
    session, url_for, flash
)
from functools import wraps
import sqlite3
import qrcode
import io
import secrets
import os
from datetime import date
from typing import Dict, Any

# ===== i18n 初期化 =====
#  extras/i18n.py を読み込んで、Jinja2とPython側の両方で _() を使えるようにする
from extras.i18n import init_i18n, _, get_current_lang

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "care.db")

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
init_i18n(app)  # <- これが多言語機能のオン

# -------------------------
# DBユーティリティ
# -------------------------
def get_connection():
    # Windows でも排他が起きにくい設定
    return sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)

def table_columns(conn, table_name: str):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    return [row[1] for row in cur.fetchall()]

def add_column_if_missing(conn, table: str, column: str, ddl: str):
    cols = table_columns(conn, table)
    if column not in cols:
        cur = conn.cursor()
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        conn.commit()

def init_db():
    with get_connection() as conn:
        c = conn.cursor()

        # 利用者
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

        # 記録
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

        # スタッフ
        c.execute("""
        CREATE TABLE IF NOT EXISTS staff(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT UNIQUE,
          password TEXT,
          role TEXT,
          login_token TEXT
        )
        """)

        # 引継ぎ
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

        # 既存DBの不足カラムを自動補完
        add_column_if_missing(conn, "users",   "room_number", "TEXT")
        add_column_if_missing(conn, "users",   "notes",       "TEXT")
        add_column_if_missing(conn, "records", "staff_name",  "TEXT")

        conn.commit()

# 初回起動時にDB作成/補修
if not os.path.exists(DB_PATH):
    init_db()
else:
    # 既存DBでも不足カラムを足す
    init_db()

# -------------------------
# デコレータ（認証/権限）
# -------------------------
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
            return "❌ " + _("管理者権限が必要です。"), 403
        return f(*args, **kwargs)
    return wrapper

# -------------------------
# 言語切替
# -------------------------
@app.route("/set_language/<lang>")
def set_language(lang):
    if lang not in ("ja", "en"):
        lang = "ja"
    session["lang"] = lang
    return redirect(request.headers.get("Referer") or url_for("home"))

# -------------------------
# ホーム
# -------------------------
@app.route("/")
def home():
    return render_template(
        "home.html",
        staff_name=session.get("staff_name"),
        staff_role=session.get("staff_role"),
        current_lang=get_current_lang()
    )

# -------------------------
# スタッフ登録/ログイン/ログアウト
# -------------------------
@app.route("/staff_register", methods=["GET", "POST"])
def staff_register():
    if request.method == "POST":
        name = request.form.get("name")
        password = request.form.get("password")
        role = "caregiver"
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
            flash(_("同名のスタッフが既に存在します。"))
    return render_template("staff_register.html", current_lang=get_current_lang())

@app.route("/staff_login", methods=["GET", "POST"])
def staff_login():
    if request.method == "POST":
        name = request.form.get("name")
        password = request.form.get("password")
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT name, role FROM staff WHERE name=? AND password=?", (name, password))
            staff = c.fetchone()
        if staff:
            session["staff_name"] = staff[0]
            session["staff_role"] = staff[1]
            flash(_("{} さんでログインしました。").format(staff[0]))
            return redirect(url_for("home"))
        else:
            flash(_("名前またはパスワードが違います。"))
    return render_template("staff_login.html", current_lang=get_current_lang())

@app.route("/logout")
def logout():
    session.clear()
    flash(_("ログアウトしました。"))
    return redirect(url_for("home"))

# -------------------------
# 管理ページ
# -------------------------
@app.route("/admin")
@admin_required
def admin_page():
    return render_template("admin.html",
                           staff_name=session.get("staff_name"),
                           current_lang=get_current_lang())

# スタッフ一覧/QR/削除
@app.route("/staff_list")
@admin_required
def staff_list():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, password, role, login_token FROM staff ORDER BY id")
        staff = c.fetchall()
    return render_template("staff_list.html", staff_list=staff, current_lang=get_current_lang())

@app.route("/qr/<name>")
@admin_required
def qr_reissue(name):
    token = secrets.token_hex(8)
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE staff SET login_token=? WHERE name=?", (token, name))
        conn.commit()
    flash(_("QRを再発行しました。"))
    return redirect(url_for("staff_list"))

@app.route("/delete_staff/<int:sid>")
@admin_required
def delete_staff(sid):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM staff WHERE id=?", (sid,))
        conn.commit()
    flash(_("削除しました。"))
    return redirect(url_for("staff_list"))

# QRコード画像を生成（新規登録/更新）
@app.route("/generate_qr", methods=["GET", "POST"])
@admin_required
def generate_qr():
    if request.method == "POST":
        name = request.form.get("name")
        role = request.form.get("role") or "caregiver"
        token = secrets.token_hex(8)
        with get_connection() as conn:
            c = conn.cursor()
            # 同名があれば上書き
            c.execute("""
                INSERT INTO staff(name, role, login_token)
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
    return render_template("generate_qr.html", current_lang=get_current_lang())

@app.route("/login/<token>")
def login_by_qr(token):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT name, role FROM staff WHERE login_token=?", (token,))
        staff = c.fetchone()
    if not staff:
        return "❌ " + _("無効なQRコードです。"), 403
    session["staff_name"] = staff[0]
    session["staff_role"] = staff[1]
    flash(_("{} さんでログインしました。").format(staff[0]))
    return redirect(url_for("home"))

# -------------------------
# 利用者（一覧/追加/削除）
# -------------------------
@app.route("/users")
@admin_required
def users_page():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, age, gender, room_number, notes FROM users ORDER BY id")
        users = c.fetchall()
    return render_template("users.html", users=users, current_lang=get_current_lang())

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
            c.execute("""
                INSERT INTO users(name, age, gender, room_number, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (name, age, gender, room_number, notes))
            conn.commit()
        flash(_("利用者を登録しました。"))
        return redirect(url_for("users_page"))
    return render_template("add_user.html", current_lang=get_current_lang())

@app.route("/delete_user/<int:user_id>")
@admin_required
def delete_user(user_id):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
    flash(_("削除しました。"))
    return redirect(url_for("users_page"))

# -------------------------
# 記録（一覧/追加=選択式）
# -------------------------
@app.route("/records")
@login_required
def records():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
          SELECT r.id, u.name, r.meal, r.medication, r.toilet, r.condition, r.memo, r.staff_name, r.created_at
          FROM records r
          JOIN users u ON r.user_id = u.id
          ORDER BY r.id DESC
        """)
        rows = c.fetchall()
    return render_template("records.html", rows=rows, current_lang=get_current_lang())

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
        memo = request.form.get("memo") or ""
        staff_name = session.get("staff_name")

        with get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO records(user_id, meal, medication, toilet, condition, memo, staff_name)
                VALUES(?, ?, ?, ?, ?, ?, ?)
            """, (user_id, meal, medication, toilet, condition, memo, staff_name))
            conn.commit()
        flash(_("記録を保存しました。"))
        return redirect(url_for("records"))

    return render_template(
        "add_record.html",
        users=users,
        MEAL_CHOICES=MEAL_CHOICES,
        MEDICATION_CHOICES=MEDICATION_CHOICES,
        TOILET_CHOICES=TOILET_CHOICES,
        CONDITION_CHOICES=CONDITION_CHOICES,
        current_lang=get_current_lang()
    )

# -------------------------
# 引継ぎボード（一覧/追加）
# -------------------------
@app.route("/handover", methods=["GET"])
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
            WHERE h.on_date=? AND h.shift=?
            ORDER BY h.priority ASC, h.id DESC
        """, (on_date, shift))
        items = c.fetchall()
    return render_template("handover.html",
                           items=items, residents=residents,
                           on_date=on_date, shift=shift,
                           current_lang=get_current_lang())

@app.route("/handover/add", methods=["POST"])
@login_required
def handover_add():
    on_date = request.form.get("on_date") or date.today().isoformat()
    shift = request.form.get("shift") or "day"
    resident_id = request.form.get("resident_id")
    priority = request.form.get("priority") or 2
    title = request.form.get("title") or ""
    body = request.form.get("body") or ""
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
          INSERT INTO handover(on_date, shift, resident_id, priority, title, body)
          VALUES (?, ?, ?, ?, ?, ?)
        """, (on_date, shift, resident_id, priority, title, body))
        conn.commit()
    flash(_("引継ぎを追加しました。"))
    return redirect(url_for("handover", date=on_date, shift=shift))

# -------------------------
# エントリポイント
# -------------------------
if __name__ == "__main__":
    # 0.0.0.0 でローカルLANからもアクセス可
    app.run(host="0.0.0.0", port=5000, debug=True)
