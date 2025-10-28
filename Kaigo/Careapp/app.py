from flask import (
    Flask, render_template, request, redirect, send_file,
    session, url_for, flash, g
)
from functools import wraps
import sqlite3
import qrcode
import io
import secrets
import os
from datetime import date
from extras.i18n import get_i18n

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# ===== DB =====
DB_PATH = "care.db"

def get_connection():
    return sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)

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
              role TEXT,          -- 'admin' / 'caregiver'
              login_token TEXT
            )
        """)
        # 引継ぎ
        c.execute("""
            CREATE TABLE IF NOT EXISTS handover(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              on_date TEXT,       -- 'YYYY-MM-DD'
              shift TEXT,         -- 'day'/'evening'/'night'
              resident_id INTEGER,
              priority INTEGER,   -- 1:高 2:中 3:低
              title TEXT,
              body TEXT,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

if not os.path.exists(DB_PATH):
    init_db()

# ===== i18n: 言語切替 & コンテキスト注入 =====
@app.before_request
def _bind_i18n():
    lang = session.get("lang", "ja")
    g._ = get_i18n(lang)
    g.current_lang = lang

@app.context_processor
def _inject_i18n():
    return {"_": g._, "current_lang": g.current_lang}

@app.route("/set_language/<lang>")
def set_language(lang):
    if lang not in ("ja", "en"):
        lang = "ja"
    session["lang"] = lang
    return redirect(request.referrer or url_for("home"))

# ===== 認証デコレータ =====
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "staff_name" not in session:
            flash(g._("ログインが必要です。"))
            return redirect(url_for("staff_login"))
        return f(*args, **kwargs)
    return wrapper

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("staff_role") != "admin":
            return "❌ " + g._("管理者"), 403
        return f(*args, **kwargs)
    return wrapper

# ===== ホーム =====
@app.route("/")
def home():
    return render_template("home.html",
                           staff_name=session.get("staff_name"),
                           staff_role=session.get("staff_role"))

# ===== スタッフ登録 / ログイン / ログアウト =====
@app.route("/staff_register", methods=["GET", "POST"])
def staff_register():
    if request.method == "POST":
        name = request.form.get("name")
        password = request.form.get("password")
        role = "caregiver"
        with get_connection() as conn:
            c = conn.cursor()
            try:
                c.execute("INSERT INTO staff (name, password, role) VALUES (?, ?, ?)",
                          (name, password, role))
                conn.commit()
                flash(g._("登録完了。ログインしてください。"))
                return redirect(url_for("staff_login"))
            except sqlite3.IntegrityError:
                flash(g._("同名のスタッフがすでに存在します。"))
    return render_template("staff_login.html", mode="register")

@app.route("/staff_login", methods=["GET", "POST"])
def staff_login():
    if request.method == "POST":
        name = request.form.get("name")
        password = request.form.get("password")
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT name, role FROM staff WHERE name=? AND password=?",
                      (name, password))
            staff = c.fetchone()
        if staff:
            session["staff_name"] = staff[0]
            session["staff_role"] = staff[1]
            flash(g._("%s さんでログインしました。") % staff[0])
            return redirect(url_for("home"))
        else:
            flash(g._("名前またはパスワードが間違っています。"))
    return render_template("staff_login.html", mode="login")

@app.route("/logout")
def logout():
    session.clear()
    flash(g._("ログアウトしました。"))
    return redirect(url_for("home"))

# ===== 管理ページ & スタッフ管理 =====
@app.route("/admin")
@admin_required
def admin_page():
    return render_template("admin.html", staff_name=session.get("staff_name"))

@app.route("/admin/staff/")
@admin_required
def staff_list():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, password, role, login_token FROM staff ORDER BY id")
        staff = c.fetchall()
    return render_template("staff_list.html", staff_list=staff)

@app.route("/qr/<name>")
@admin_required
def qr_reissue(name):
    token = secrets.token_hex(8)
    with get_connection() as conn:
        c = conn.cursor()
        # 既存があれば更新、無ければ作成（roleは既存維持、無ければcaregiver）
        c.execute("SELECT id, role FROM staff WHERE name=?", (name,))
        row = c.fetchone()
        if row:
            c.execute("UPDATE staff SET login_token=? WHERE id=?", (token, row[0]))
        else:
            c.execute("INSERT INTO staff (name, password, role, login_token) VALUES (?, '', 'caregiver', ?)",
                      (name, token))
        conn.commit()

    host = request.host.split(":")[0]
    login_url = f"http://{host}:5000/login/{token}"
    img = qrcode.make(login_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

@app.route("/login/<token>")
def login_by_qr(token):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT name, role FROM staff WHERE login_token=?", (token,))
        staff = c.fetchone()
    if not staff:
        return "❌ invalid QR", 403
    session["staff_name"] = staff[0]
    session["staff_role"] = staff[1]
    flash(g._("%s さんでログインしました。") % staff[0])
    return redirect(url_for("home"))

@app.route("/delete_staff/<int:sid>")
@admin_required
def delete_staff(sid):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM staff WHERE id=?", (sid,))
        conn.commit()
    flash("OK")
    return redirect(url_for("staff_list"))

# ===== 利用者 =====
@app.route("/users")
@admin_required
def users_page():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, age, gender, room_number, notes FROM users ORDER BY id")
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
            c.execute("""
                INSERT INTO users (name, age, gender, room_number, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (name, age, gender, room_number, notes))
            conn.commit()
        flash("OK")
        return redirect(url_for("users_page"))
    return render_template("add_user.html")

@app.route("/delete_user/<int:user_id>")
@admin_required
def delete_user(user_id):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
    flash("OK")
    return redirect(url_for("users_page"))

# ===== 記録 =====
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

@app.route("/add_record", methods=["GET", "POST"])
@login_required
def add_record():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name FROM users ORDER BY id")
        users = c.fetchall()

    MEAL_CHOICES       = ["全量", "8割", "半分", "1/3", "ほぼ食べず", "その他"]
    MEDICATION_CHOICES = ["済", "一部", "未", "自己管理", "その他"]
    TOILET_CHOICES     = ["自立", "誘導", "介助", "失禁なし", "失禁あり", "その他"]
    CONDITION_CHOICES  = ["良好", "普通", "要観察", "受診", "発熱(37.5℃～)", "その他"]

    if request.method == "POST":
        def picked(val, other):
            other = (other or "").strip()
            return other if (val == "その他" and other) else val

        user_id   = request.form.get("user_id")
        meal      = picked(request.form.get("meal"),        request.form.get("meal_other"))
        medication= picked(request.form.get("medication"),  request.form.get("medication_other"))
        toilet    = picked(request.form.get("toilet"),      request.form.get("toilet_other"))
        condition = picked(request.form.get("condition"),   request.form.get("condition_other"))
        memo      = request.form.get("memo")
        staff_name= session.get("staff_name")

        with get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO records (user_id, meal, medication, toilet, condition, memo, staff_name)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, meal, medication, toilet, condition, memo, staff_name))
            conn.commit()
        flash("OK")
        return redirect(url_for("records"))

    return render_template("add_record.html",
                           users=users,
                           MEAL_CHOICES=MEAL_CHOICES,
                           MEDICATION_CHOICES=MEDICATION_CHOICES,
                           TOILET_CHOICES=TOILET_CHOICES,
                           CONDITION_CHOICES=CONDITION_CHOICES)

# ===== 引継ぎ =====
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
            INSERT INTO handover (on_date, shift, resident_id, priority, title, body)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (on_date, shift, resident_id, priority, title, body))
        conn.commit()
    flash("OK")
    return redirect(url_for("handover", date=on_date, shift=shift))

# ===== 起動 =====
if __name__ == "__main__":
    # 既存DBでも安全に起動できるよう念のため
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
