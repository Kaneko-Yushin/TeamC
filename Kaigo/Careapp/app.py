from flask import (
    Flask, render_template, request, redirect, send_file,
    session, url_for, flash, Response
)
from functools import wraps
import sqlite3
import qrcode
import io
import secrets
import os
import csv
from datetime import date
import gettext

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
DB_PATH = "care.db"

# ==============================
# 🔤 i18n 多言語化設定
# ==============================
SUPPORTED_LANGS = ["ja", "en"]

def get_locale():
    """セッションから現在の言語を取得"""
    lang = session.get("lang") or "ja"
    return lang if lang in SUPPORTED_LANGS else "ja"

def load_translations(lang: str):
    """指定言語の翻訳ファイルを読み込み"""
    try:
        t = gettext.translation(
            domain="messages",
            localedir="translations",
            languages=[lang]
        )
        return t.gettext
    except Exception:
        return gettext.gettext  # moが無くても原文を返す

# ---- Pythonコード内でも使える _() ----
def _(message: str) -> str:
    """Python側用の翻訳関数"""
    return load_translations(get_locale())(message)

@app.before_request
def _inject_gettext():
    """Jinja2側にも _ を登録"""
    app.jinja_env.globals["_"] = _
    app.jinja_env.globals["current_lang"] = get_locale()

@app.route("/set_language/<lang>")
def set_language(lang):
    """言語切替ルート"""
    if lang not in SUPPORTED_LANGS:
        lang = "ja"
    session["lang"] = lang
    ref = request.headers.get("Referer")
    return redirect(ref or url_for("home"))

# ==============================
# 💾 DB接続設定
# ==============================
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

# ==============================
# 🧩 デコレータ
# ==============================
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

# ==============================
# 🏠 ホーム
# ==============================
@app.route("/")
def home():
    staff_name = session.get("staff_name")
    staff_role = session.get("staff_role")
    return render_template("home.html", staff_name=staff_name, staff_role=staff_role)

# ==============================
# 👩‍⚕️ スタッフ登録・ログイン
# ==============================
@app.route("/staff_register", methods=["GET", "POST"])
def staff_register():
    if request.method == "POST":
        name = request.form.get("name")
        password = request.form.get("password")
        role = "caregiver"
        with get_connection() as conn:
            c = conn.cursor()
            try:
                c.execute("INSERT INTO staff (name, password, role) VALUES (?, ?, ?)", (name, password, role))
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
            c.execute("SELECT name, role FROM staff WHERE name=? AND password=?", (name, password))
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

# ==============================
# 👥 利用者管理
# ==============================
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
            c.execute("INSERT INTO users (name, age, gender, room_number, notes) VALUES (?, ?, ?, ?, ?)",
                      (name, age, gender, room_number, notes))
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

# ==============================
# 📋 記録管理
# ==============================
@app.route("/records")
@login_required
def records():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT r.id, u.name, r.meal, r.medication, r.toilet, r.condition,
                   r.memo, r.staff_name, r.created_at
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

    MEAL_CHOICES = [_("全量"), _("8割"), _("半分"), _("1/3"), _("ほぼ食べず"), _("その他")]
    MEDICATION_CHOICES = [_("済"), _("一部"), _("未"), _("自己管理"), _("その他")]
    TOILET_CHOICES = [_("自立"), _("誘導"), _("介助"), _("失禁なし"), _("失禁あり"), _("その他")]
    CONDITION_CHOICES = [_("良好"), _("普通"), _("要観察"), _("受診"), _("発熱(37.5℃～)"), _("その他")]

    if request.method == "POST":
        def picked(val, other):
            other = (other or "").strip()
            return other if (val == _("その他") and other) else val

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

    return render_template(
        "add_record.html",
        users=users,
        MEAL_CHOICES=MEAL_CHOICES,
        MEDICATION_CHOICES=MEDICATION_CHOICES,
        TOILET_CHOICES=TOILET_CHOICES,
        CONDITION_CHOICES=CONDITION_CHOICES
    )

# ==============================
# 🔄 引継ぎボード
# ==============================
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
            WHERE h.on_date = ? AND h.shift = ?
            ORDER BY h.priority ASC, h.id DESC
        """, (on_date, shift))
        items = c.fetchall()
    return render_template("handover.html", items=items, residents=residents, on_date=on_date, shift=shift)

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

# ==============================
# ⚙️ 管理者ページ・スタッフ管理
# ==============================
@app.route("/admin")
@admin_required
def admin_page():
    staff_name = session.get("staff_name")
    return render_template("admin.html", staff_name=staff_name)

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
        c.execute("DELETE FROM staff WHERE id = ?", (sid,))
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
    flash(_("QRトークンを再発行しました。"))
    return redirect(url_for("staff_list"))

# ==============================
# 📱 QRコードログイン
# ==============================
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
                "INSERT OR REPLACE INTO staff (name, role, login_token) VALUES (?, ?, ?)",
                (name, role, token)
            )
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
    else:
        return _("❌ 無効なQRコードです。再発行してください。"), 403

# ==============================
# 🚀 メイン実行
# ==============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
