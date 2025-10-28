from flask import Flask, render_template, request, redirect, send_file, session, url_for, flash, g
from functools import wraps
import sqlite3
import qrcode
import io
import secrets
import os
from datetime import date
import gettext

# -----------------------------
# Flask設定
# -----------------------------
app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
DB_PATH = "care.db"

# -----------------------------
# 多言語設定
# -----------------------------
SUPPORTED_LANGS = ["ja", "en"]
DEFAULT_LANG = "ja"

def get_lang():
    lang = session.get("lang")
    if not lang:
        lang = request.accept_languages.best_match(SUPPORTED_LANGS)
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG
    return lang

def _get_translator(lang):
    localedir = os.path.join(app.root_path, "translations")
    try:
        trans = gettext.translation("messages", localedir=localedir, languages=[lang])
        trans.install()
        _ = trans.gettext
    except Exception:
        gettext.install("messages")
        _ = gettext.gettext
    return _

@app.before_request
def before_request():
    g.CURRENT_LANG = get_lang()
    g._ = _get_translator(g.CURRENT_LANG)

@app.context_processor
def inject_globals():
    return {"CURRENT_LANG": getattr(g, "CURRENT_LANG", DEFAULT_LANG), "_": getattr(g, "_", lambda s: s)}

@app.route("/set_language/<lang>")
def set_language(lang):
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG
    session["lang"] = lang
    return redirect(request.referrer or url_for("home"))

# -----------------------------
# DBユーティリティ
# -----------------------------
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
        conn.commit()

if not os.path.exists(DB_PATH):
    init_db()

# -----------------------------
# 認証デコレータ
# -----------------------------
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
        if "staff_role" not in session or session["staff_role"] != "admin":
            return _("❌ 管理者権限が必要です。"), 403
        return f(*args, **kwargs)
    return wrapper

# -----------------------------
# ホーム
# -----------------------------
@app.route("/")
def home():
    return render_template("home.html",
                           staff_name=session.get("staff_name"),
                           staff_role=session.get("staff_role"))

# -----------------------------
# スタッフ登録・ログイン
# -----------------------------
@app.route("/staff_register", methods=["GET", "POST"])
def staff_register():
    if request.method == "POST":
        name = request.form["name"]
        password = request.form["password"]
        role = "caregiver"
        try:
            with get_connection() as conn:
                c = conn.cursor()
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
        name = request.form["name"]
        password = request.form["password"]
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT name, role FROM staff WHERE name=? AND password=?", (name, password))
            staff = c.fetchone()
        if staff:
            session["staff_name"] = staff[0]
            session["staff_role"] = staff[1]
            flash(_("%(name)s さんでログインしました。", name=staff[0]))
            return redirect(url_for("home"))
        else:
            flash(_("名前またはパスワードが間違っています。"))
    return render_template("staff_login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash(_("ログアウトしました。"))
    return redirect(url_for("home"))

# -----------------------------
# 利用者管理
# -----------------------------
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
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("INSERT INTO users (name, age, gender, room_number, notes) VALUES (?, ?, ?, ?, ?)",
                      (request.form["name"], request.form["age"], request.form["gender"],
                       request.form["room_number"], request.form["notes"]))
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

# -----------------------------
# 記録管理
# -----------------------------
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
    MED_CHOICES = ["済", "一部", "未", "自己管理", "その他"]
    TOI_CHOICES = ["自立", "誘導", "介助", "失禁なし", "失禁あり", "その他"]
    CON_CHOICES = ["良好", "普通", "要観察", "受診", "発熱(37.5℃～)", "その他"]

    if request.method == "POST":
        def pick(val, other):
            return other.strip() if val == "その他" and other else val

        user_id = request.form["user_id"]
        meal = pick(request.form["meal"], request.form.get("meal_other", ""))
        medication = pick(request.form["medication"], request.form.get("medication_other", ""))
        toilet = pick(request.form["toilet"], request.form.get("toilet_other", ""))
        condition = pick(request.form["condition"], request.form.get("condition_other", ""))
        memo = request.form["memo"]
        staff_name = session["staff_name"]

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
                           MEDICATION_CHOICES=MED_CHOICES,
                           TOILET_CHOICES=TOI_CHOICES,
                           CONDITION_CHOICES=CON_CHOICES)

# -----------------------------
# 引継ぎ管理
# -----------------------------
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
            FROM handover h LEFT JOIN users u ON h.resident_id = u.id
            WHERE h.on_date=? AND h.shift=?
            ORDER BY h.priority ASC, h.id DESC
        """, (on_date, shift))
        items = c.fetchall()
    return render_template("handover.html", items=items, residents=residents, on_date=on_date, shift=shift)

@app.route("/handover/add", methods=["POST"])
@login_required
def handover_add():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO handover(on_date, shift, resident_id, priority, title, body) VALUES (?, ?, ?, ?, ?, ?)",
                  (request.form.get("on_date", date.today().isoformat()),
                   request.form.get("shift", "day"),
                   request.form["resident_id"],
                   request.form.get("priority", 2),
                   request.form["title"],
                   request.form["body"]))
        conn.commit()
    flash(_("引継ぎを追加しました。"))
    return redirect(url_for("handover"))

# -----------------------------
# 管理者ページ & QRログイン
# -----------------------------
@app.route("/admin")
@admin_required
def admin_page():
    return render_template("admin.html", staff_name=session.get("staff_name"))

@app.route("/generate_qr", methods=["GET", "POST"])
@admin_required
def generate_qr():
    if request.method == "POST":
        name = request.form["name"]
        role = request.form.get("role", "caregiver")
        token = secrets.token_hex(8)
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO staff (name, role, login_token) VALUES (?, ?, ?)", (name, role, token))
            conn.commit()
        host = request.host.split(":")[0]
        url = f"http://{host}:5000/login/{token}"
        buf = io.BytesIO()
        qrcode.make(url).save(buf, format="PNG")
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
        flash(_("%(name)s さんでログインしました。", name=staff[0]))
        return redirect(url_for("home"))
    return _("無効なQRコードです。"), 403

# -----------------------------
# メイン起動
# -----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
