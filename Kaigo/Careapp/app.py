# app.py  — 完全版（Blueprint未使用／多言語対応／全機能搭載）
from flask import Flask, render_template, request, redirect, send_file, session, url_for, flash
from functools import wraps
import sqlite3, qrcode, io, secrets, os, csv
from datetime import date
from flask_babel import Babel, gettext as _
from markupsafe import Markup

APP_SECRET = os.environ.get("APP_SECRET") or secrets.token_hex(16)
DB_PATH = "care.db"

app = Flask(__name__)
app.secret_key = APP_SECRET

# --------- Babel (Flask-Babel >=3 系) ----------
app.config["BABEL_DEFAULT_LOCALE"] = "ja"
app.config["BABEL_DEFAULT_TIMEZONE"] = "Asia/Tokyo"
app.config["LANGUAGES"] = ["ja", "en"]
babel = Babel(app)

def get_locale():
    # 1) セッションの選択 2) ブラウザの優先
    lang = session.get("lang")
    if lang in app.config["LANGUAGES"]:
        return lang
    return request.accept_languages.best_match(app.config["LANGUAGES"]) or "ja"

babel.init_app(app, locale_selector=get_locale)
# Jinja から _('...') を必ず呼べるように
app.jinja_env.globals.update(_=_)

# --------- DB 接続 ----------
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
              role TEXT,          -- 'admin' or 'caregiver'
              login_token TEXT    -- QRログイン用
            )
        """)
        # 引継ぎ（新カラムを含む）
        c.execute("""
            CREATE TABLE IF NOT EXISTS handover(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              h_date TEXT,     -- 2025-10-31 など
              shift TEXT,      -- day/eve/night
              resident_id INTEGER,
              priority INTEGER,
              title TEXT,
              note TEXT,       -- 本文
              staff TEXT,      -- 記入者
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

# 既存DBがあって古い列名を使っている可能性に備えた軽量マイグレーション
def safe_migrate():
    with get_connection() as conn:
        c = conn.cursor()

        def col_exists(table, col):
            c.execute(f"PRAGMA table_info({table})")
            return any(r[1] == col for r in c.fetchall())

        # handover: on_date→h_date 短絡コピー
        if col_exists("handover", "on_date") and not col_exists("handover", "h_date"):
            c.execute("ALTER TABLE handover ADD COLUMN h_date TEXT")
            c.execute("UPDATE handover SET h_date = on_date")
            conn.commit()
        # handover: staff / note の不足補完
        if not col_exists("handover", "staff"):
            c.execute("ALTER TABLE handover ADD COLUMN staff TEXT")
        if not col_exists("handover", "note"):
            c.execute("ALTER TABLE handover ADD COLUMN note TEXT")
        conn.commit()

if not os.path.exists(DB_PATH):
    init_db()
else:
    # 既存DBでも最低限の互換を確保
    safe_migrate()

# --------- 認証デコレータ ----------
def login_required(f):
    @wraps(f)
    def w(*a, **kw):
        if "staff_name" not in session:
            flash(_("ログインが必要です。"))
            return redirect(url_for("staff_login"))
        return f(*a, **kw)
    return w

def admin_required(f):
    @wraps(f)
    def w(*a, **kw):
        if session.get("staff_role") != "admin":
            return _("❌ 管理者権限が必要です。"), 403
        return f(*a, **kw)
    return w

# --------- 言語切替 ----------
@app.route("/set_language/<lang>")
def set_language(lang):
    lang = lang.lower()
    if lang in app.config["LANGUAGES"]:
        session["lang"] = lang
        flash(_("言語を切り替えました。"))
    return redirect(request.referrer or url_for("home"))

# --------- ホーム ----------
@app.route("/")
def home():
    return render_template("home.html")

# --------- スタッフ登録／ログイン／ログアウト ----------
@app.route("/staff_register", methods=["GET", "POST"])
def staff_register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "").strip()
        role = "caregiver"
        if not name or not password:
            flash(_("名前とパスワードを入力してください。"))
            return redirect(url_for("staff_register"))
        with get_connection() as conn:
            c = conn.cursor()
            try:
                c.execute("INSERT INTO staff (name, password, role) VALUES (?, ?, ?)", (name, password, role))
                conn.commit()
                flash(_("登録完了。ログインしてください。"))
                return redirect(url_for("staff_login"))
            except sqlite3.IntegrityError:
                flash(_("同名のスタッフがすでに存在します。"))
    return render_template("staff_register.html")

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
            flash(_("%(n)s さんでログインしました。", n=staff[0]))
            return redirect(url_for("home"))
        else:
            flash(_("名前またはパスワードが間違っています。"))
    return render_template("staff_login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash(_("ログアウトしました。"))
    return redirect(url_for("home"))

# --------- 管理ページ＆スタッフ管理 ----------
@app.route("/admin")
@admin_required
def admin_page():
    return render_template("admin.html")

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

@app.route("/qr_reissue/<name>")
@admin_required
def qr_reissue(name):
    token = secrets.token_hex(8)
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE staff SET login_token=? WHERE name=?", (token, name))
        conn.commit()
    flash(_("QRを再発行しました。"))
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
            # 既存行があれば上書き、なければ作成
            c.execute("""
                INSERT INTO staff(name, role, login_token)
                VALUES(?,?,?)
                ON CONFLICT(name) DO UPDATE SET role=excluded.role, login_token=excluded.login_token
            """, (name, role, token))
            conn.commit()
        # ログインURLをQR化
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
    if not staff:
        return _("無効なQRコードです。"), 403
    session["staff_name"] = staff[0]
    session["staff_role"] = staff[1]
    flash(_("%(n)s さんでログインしました。", n=staff[0]))
    return redirect(url_for("home"))

# --------- 利用者 ----------
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
                INSERT INTO users(name, age, gender, room_number, notes)
                VALUES(?,?,?,?,?)
            """, (name, age, gender, room_number, notes))
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

# --------- 記録（一覧＋追加・選択式） ----------
@app.route("/records")
@login_required
def records():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT r.id, u.name, r.meal, r.medication, r.toilet, r.condition, r.memo, r.staff_name, r.created_at
            FROM records r JOIN users u ON r.user_id = u.id
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

# --------- 引継ぎ ----------
@app.route("/handover", methods=["GET"])
@login_required
def handover():
    h_date = request.args.get("date") or date.today().isoformat()
    shift = request.args.get("shift") or "day"
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name FROM users ORDER BY id")
        residents = c.fetchall()
        c.execute("""
            SELECT h.id, h.h_date, h.shift, u.name, h.priority, h.title, h.note, h.staff, h.created_at
            FROM handover h LEFT JOIN users u ON h.resident_id = u.id
            WHERE h.h_date = ? AND h.shift = ?
            ORDER BY h.priority ASC, h.id DESC
        """, (h_date, shift))
        items = c.fetchall()
    return render_template("handover.html", items=items, residents=residents, h_date=h_date, shift=shift)

@app.route("/handover/add", methods=["POST"])
@login_required
def handover_add():
    h_date = request.form.get("h_date") or date.today().isoformat()
    shift = request.form.get("shift") or "day"
    resident_id = request.form.get("resident_id")
    priority = request.form.get("priority") or 2
    title = request.form.get("title")
    note = request.form.get("note")
    staff_name = session.get("staff_name")
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO handover(h_date, shift, resident_id, priority, title, note, staff)
            VALUES (?,?,?,?,?,?,?)
        """, (h_date, shift, resident_id, priority, title, note, staff_name))
        conn.commit()
    flash(_("引継ぎを追加しました。"))
    return redirect(url_for("handover", date=h_date, shift=shift))

# --------- 404 ----------
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

# --------- 起動 ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
