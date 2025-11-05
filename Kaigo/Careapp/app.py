# app.py — 宿題２ 完全版（QR画像エンドポイント・generate_qrのnames対応・/handover POST対応）
from flask import Flask, render_template, request, redirect, send_file, session, url_for, flash
from functools import wraps
import sqlite3, qrcode, io, secrets, os
from datetime import date
from flask_babel import Babel, gettext as _

APP_SECRET = os.environ.get("APP_SECRET") or os.urandom(16)
DB_PATH = os.environ.get("DB_PATH") or os.path.join(os.path.dirname(__file__), "care.db")

app = Flask(__name__)
app.secret_key = APP_SECRET

# ------------ Babel (Flask-Babel v3系) ------------
app.config["BABEL_DEFAULT_LOCALE"] = "ja"
app.config["BABEL_DEFAULT_TIMEZONE"] = "Asia/Tokyo"
app.config["LANGUAGES"] = ["ja", "en"]
babel = Babel(app)


def get_locale():
    # 1) セッション選択 > 2) ブラウザ優先
    lang = session.get("lang")
    if lang in app.config["LANGUAGES"]:
        return lang
    return request.accept_languages.best_match(app.config["LANGUAGES"]) or "ja"


babel.init_app(app, locale_selector=get_locale)
app.jinja_env.globals.update(_=_, get_locale=get_locale)

# ------------ DB ------------

def get_connection():
    return sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)


def init_db():
    with get_connection() as conn:
        c = conn.cursor()
        # users
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS users(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT,
              age INTEGER,
              gender TEXT,
              room_number TEXT,
              notes TEXT
            )
            """
        )
        # records
        c.execute(
            """
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
            """
        )
        # staff
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS staff(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT UNIQUE,
              password TEXT,
              role TEXT,
              login_token TEXT
            )
            """
        )
        # handover（新スキーマ）
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS handover(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              h_date TEXT,
              shift TEXT,
              resident_id INTEGER,
              priority INTEGER,
              title TEXT,
              note TEXT,
              staff TEXT,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def safe_migrate():
    """既存DBの不足カラムや旧名を補修。何度呼んでも安全。"""
    with get_connection() as conn:
        c = conn.cursor()

        def cols(table):
            c.execute(f"PRAGMA table_info({table})")
            return {r[1] for r in c.fetchall()}

        # users 補修
        cu = cols("users")
        if "room_number" not in cu:
            c.execute("ALTER TABLE users ADD COLUMN room_number TEXT")
        if "notes" not in cu:
            c.execute("ALTER TABLE users ADD COLUMN notes TEXT")

        # records 補修
        cr = cols("records")
        if "staff_name" not in cr:
            c.execute("ALTER TABLE records ADD COLUMN staff_name TEXT")
        if "created_at" not in cr:
            c.execute("ALTER TABLE records ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")

        # staff 補修
        cs = cols("staff")
        if "password" not in cs:
            c.execute("ALTER TABLE staff ADD COLUMN password TEXT")
        if "role" not in cs:
            c.execute("ALTER TABLE staff ADD COLUMN role TEXT")
        if "login_token" not in cs:
            c.execute("ALTER TABLE staff ADD COLUMN login_token TEXT")

        # handover：旧 on_date -> h_date、body -> note、created_by -> staff
        ch = cols("handover")
        if "h_date" not in ch:
            c.execute("ALTER TABLE handover ADD COLUMN h_date TEXT")
        if "note" not in ch:
            c.execute("ALTER TABLE handover ADD COLUMN note TEXT")
        if "staff" not in ch:
            c.execute("ALTER TABLE handover ADD COLUMN staff TEXT")
        if "priority" not in ch:
            c.execute("ALTER TABLE handover ADD COLUMN priority INTEGER")
        if "title" not in ch:
            c.execute("ALTER TABLE handover ADD COLUMN title TEXT")
        if "resident_id" not in ch:
            c.execute("ALTER TABLE handover ADD COLUMN resident_id INTEGER")
        if "created_at" not in ch:
            c.execute("ALTER TABLE handover ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        # 値のコピー（存在する場合のみ）
        if "on_date" in ch:
            c.execute("UPDATE handover SET h_date = COALESCE(h_date, on_date)")
        if "body" in ch:
            c.execute("UPDATE handover SET note = COALESCE(note, body)")
        if "content" in ch:
            c.execute("UPDATE handover SET note = COALESCE(note, content)")
        if "created_by" in ch:
            c.execute("UPDATE handover SET staff = COALESCE(staff, created_by)")

        conn.commit()


if not os.path.exists(DB_PATH):
    init_db()
else:
    safe_migrate()

# ------------ 認可デコレータ ------------

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
            return _("管理者権限が必要です。"), 403
        return f(*a, **kw)
    return w

# ------------ 言語切替 ------------
@app.route("/set_language/<lang>")
def set_language(lang):
    lang = (lang or "ja").lower()
    if lang in app.config["LANGUAGES"]:
        session["lang"] = lang
        flash(_("言語を切り替えました。"))
    return redirect(request.referrer or url_for("home"))

# ------------ ホーム ------------
@app.route("/")
def home():
    return render_template("home.html")

# ------------ スタッフ登録/ログイン/ログアウト ------------
@app.route("/staff_register", methods=["GET", "POST"])
def staff_register():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        password = (request.form.get("password") or "").strip()
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

# ------------ 管理ページ & スタッフ管理 ------------
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


# ★ 追加: QR画像エンドポイント（staff_list.html が img src で参照）
@app.route("/qr/<token>.png")
@admin_required
def qr_png(token):
    host = request.host.split(":")[0]
    login_url = f"http://{host}:5000/login/{token}"
    img = qrcode.make(login_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/generate_qr", methods=["GET", "POST"])
@admin_required
def generate_qr():
    if request.method == "POST":
        name = request.form.get("name")
        role = request.form.get("role") or "caregiver"
        token = secrets.token_hex(8)
        with get_connection() as conn:
            c = conn.cursor()
            c.execute(
                """
                INSERT INTO staff(name, role, login_token)
                VALUES(?,?,?)
                ON CONFLICT(name) DO UPDATE SET role=excluded.role, login_token=excluded.login_token
                """,
                (name, role, token),
            )
            conn.commit()
        host = request.host.split(":")[0]
        login_url = f"http://{host}:5000/login/{token}"
        img = qrcode.make(login_url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return send_file(buf, mimetype="image/png")

    # ★ 追加: GET時に names を渡してテンプレ側のプルダウンを埋める
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT name FROM staff ORDER BY id")
        names = [row[0] for row in c.fetchall()]
    return render_template("generate_qr.html", names=names)


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

# ------------ 利用者 ------------
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
            c.execute(
                """
                INSERT INTO users(name, age, gender, room_number, notes)
                VALUES(?,?,?,?,?)
                """,
                (name, age, gender, room_number, notes),
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

# ------------ 記録 ------------
@app.route("/records")
@login_required
def records():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT r.id, u.name, r.meal, r.medication, r.toilet, r.condition, r.memo, r.staff_name, r.created_at
            FROM records r JOIN users u ON r.user_id = u.id
            ORDER BY r.id DESC
            """
        )
        rows = c.fetchall()
    return render_template("records.html", rows=rows)


@app.route("/add_record", methods=["GET", "POST"])
@login_required
def add_record():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name FROM users ORDER BY id")
        users = c.fetchall()

    if request.method == "POST":
        def picked(val, other):
            other = (other or "").strip()
            return other if (val in ("その他", "Other") and other) else val

        user_id = request.form.get("user_id")
        meal = picked(request.form.get("meal"), request.form.get("meal_other"))
        medication = picked(request.form.get("medication"), request.form.get("medication_other"))
        toilet = picked(request.form.get("toilet"), request.form.get("toilet_other"))
        condition = picked(request.form.get("condition"), request.form.get("condition_other"))
        memo = request.form.get("memo")
        staff_name = session.get("staff_name")

        with get_connection() as conn:
            c = conn.cursor()
            c.execute(
                """
                INSERT INTO records (user_id, meal, medication, toilet, condition, memo, staff_name)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, meal, medication, toilet, condition, memo, staff_name),
            )
            conn.commit()
        flash(_("記録を保存しました。"))
        return redirect(url_for("records"))

    return render_template("add_record.html", users=users)

# ------------ 引継ぎ（/handover を GET/POST 兼用にして handover.html と整合） ------------
@app.route("/handover", methods=["GET", "POST"])
@login_required
def handover():
    if request.method == "POST":
        h_date = request.form.get("h_date") or date.today().isoformat()
        shift = request.form.get("shift") or "day"
        note = request.form.get("note") or ""
        staff = (request.form.get("staff") or session.get("staff_name") or "").strip()
        with get_connection() as conn:
            c = conn.cursor()
            c.execute(
                """
                INSERT INTO handover(h_date, shift, note, staff)
                VALUES(?,?,?,?)
                """,
                (h_date, shift, note, staff),
            )
            conn.commit()
        flash(_("引継ぎを追加しました。"))
        return redirect(url_for("handover"))

    # GET: 当日分の一覧
    today = date.today().isoformat()
    h_date = request.args.get("date") or today
    shift = request.args.get("shift") or "day"
    with get_connection() as conn:
        c = conn.cursor()
        # handover.html の列構成に合わせて取得
        c.execute(
            """
            SELECT id, h_date, shift, note, staff
            FROM handover
            WHERE h_date=? AND shift=?
            ORDER BY id DESC
            """,
            (h_date, shift),
        )
        rows = c.fetchall()
    return render_template("handover.html", rows=rows, today=today)

# ------------ favicon / 404 ------------
@app.route('/favicon.ico')
def favicon():
    from flask import send_from_directory
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico', mimetype='image/vnd.microsoft.icon')


@app.errorhandler(404)
def not_found(e):
    try:
        return render_template("404.html"), 404
    except Exception:
        return "Not Found", 404

@app.context_processor
def inject_lang():
    return {"CURRENT_LANG": get_locale()}

# ------------ 起動 ------------
if __name__ == "__main__":
    # 管理系がこのDBを参照する場合用にパスを共有
    app.config["DB_PATH"] = DB_PATH
    app.run(host="0.0.0.0", port=5000, debug=True)
