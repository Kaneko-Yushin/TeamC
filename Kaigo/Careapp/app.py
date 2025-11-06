from flask import Flask, render_template, request, redirect, send_file, send_from_directory, session, url_for, flash
from functools import wraps
import sqlite3, qrcode, io, secrets, os, json
from datetime import date
from flask_babel import Babel

# -------------------- 基本設定 --------------------
APP_SECRET = os.environ.get("APP_SECRET") or os.urandom(16)
DB_PATH = os.environ.get("DB_PATH") or os.path.join(os.path.dirname(__file__), "care.db")

app = Flask(__name__)
app.secret_key = APP_SECRET

# -------------------- Babel設定（言語選択のみ） --------------------
app.config["BABEL_DEFAULT_LOCALE"] = "ja"
app.config["BABEL_DEFAULT_TIMEZONE"] = "Asia/Tokyo"
app.config["LANGUAGES"] = ["ja", "en"]

babel = Babel(app)

def get_locale():
    lang = session.get("lang")
    if lang in app.config["LANGUAGES"]:
        return lang
    return request.accept_languages.best_match(app.config["LANGUAGES"]) or "ja"

babel.init_app(app, locale_selector=get_locale)

# -------------------- JSON翻訳辞書 --------------------
def _load_json_translations():
    data = {}
    for lang in app.config["LANGUAGES"]:
        path = os.path.join(app.root_path, f"{lang}.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                try:
                    data[lang] = json.load(f)
                except Exception as e:
                    print(f"[i18n] Failed to load {lang}.json:", e)
                    data[lang] = {}
        else:
            data[lang] = {}
    return data

TRANSLATIONS = _load_json_translations()

def _t(key, **kwargs):
    """JSON辞書から翻訳を返す"""
    lang = get_locale()
    s = TRANSLATIONS.get(lang, {}).get(key, key)
    if kwargs:
        try:
            s = s % kwargs
        except Exception:
            pass
    return s

# Python側でも使えるように
_ = _t
app.jinja_env.globals.update(_=_, get_locale=get_locale)

# -------------------- i18n再読み込み・デバッグ --------------------
@app.route("/i18n/reload")
def i18n_reload():
    global TRANSLATIONS
    TRANSLATIONS = _load_json_translations()
    flash(_("言語を切り替えました。"))
    return redirect(request.referrer or url_for("home"))

@app.route("/i18n/debug")
def i18n_debug():
    lang = get_locale()
    return {
        "current_lang": lang,
        "keys_loaded": len(TRANSLATIONS.get(lang, {})),
        "example": TRANSLATIONS.get(lang, {}).get("デジタル介護日誌", None)
    }

# -------------------- DB --------------------
def get_connection():
    return sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)

def init_db():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT, age INTEGER, gender TEXT,
          room_number TEXT, notes TEXT
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS records(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER, meal TEXT, medication TEXT,
          toilet TEXT, condition TEXT, memo TEXT,
          staff_name TEXT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS staff(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT,
          password TEXT,
          role TEXT,
          login_token TEXT
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS handover(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          h_date TEXT, shift TEXT,
          note TEXT, staff TEXT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        conn.commit()

if not os.path.exists(DB_PATH):
    init_db()

# -------------------- 認可 --------------------
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

# -------------------- 言語切替 --------------------
@app.route("/set_language/<lang>")
def set_language(lang):
    lang = (lang or "ja").lower()
    if lang in app.config["LANGUAGES"]:
        session["lang"] = lang
        flash(_("言語を切り替えました。"))
    return redirect(request.referrer or url_for("home"))

# -------------------- ホーム --------------------
@app.route("/")
def home():
    return render_template("home.html")

# -------------------- スタッフ登録・ログイン --------------------
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
                c.execute("INSERT INTO staff(name, password, role) VALUES (?,?,?)", (name, password, role))
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
            row = c.fetchone()
        if row:
            session["staff_name"], session["staff_role"] = row
            flash(_("%(n)s さんでログインしました。", n=row[0]))
            return redirect(url_for("home"))
        flash(_("名前またはパスワードが間違っています。"))
    return render_template("staff_login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash(_("ログアウトしました。"))
    return redirect(url_for("home"))

# -------------------- 管理ページ --------------------
@app.route("/admin")
@admin_required
def admin_page():
    return render_template("admin.html")

# -------------------- スタッフ一覧・削除・QR --------------------
@app.route("/staff_list")
@admin_required
def staff_list():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, password, role, login_token FROM staff ORDER BY id")
        staff = c.fetchall()
    return render_template("staff_list.html", staff_list=staff)

@app.route("/delete_staff/<int:sid>", methods=["GET", "POST"], endpoint="delete_staff")
@admin_required
def delete_staff(sid):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM staff WHERE id=?", (sid,))
        conn.commit()
    flash(_("スタッフを削除しました。"))
    return redirect(url_for("staff_list"))

@app.route("/generate_qr", methods=["GET", "POST"])
@admin_required
def generate_qr():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        role = (request.form.get("role") or "caregiver").strip()
        token = secrets.token_hex(8)

        # UNIQUE制約に依存しないアップサート
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("UPDATE staff SET role=?, login_token=? WHERE name=?", (role, token, name))
            if c.rowcount == 0:
                c.execute("INSERT INTO staff(name, role, login_token) VALUES(?,?,?)", (name, role, token))
            conn.commit()

        host = request.host.split(":")[0]
        login_url = f"http://{host}:5000/login/{token}"
        img = qrcode.make(login_url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return send_file(buf, mimetype="image/png")

    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT name FROM staff ORDER BY id")
        names = [r[0] for r in c.fetchall()]
    return render_template("generate_qr.html", names=names)

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

@app.route("/login/<token>")
def login_by_qr(token):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT name, role FROM staff WHERE login_token=?", (token,))
        row = c.fetchone()
    if not row:
        return _("無効なQRコードです。"), 403
    session["staff_name"], session["staff_role"] = row
    flash(_("%(n)s さんでログインしました。", n=row[0]))
    return redirect(url_for("home"))

# -------------------- 利用者 --------------------
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
        name, age, gender = request.form.get("name"), request.form.get("age"), request.form.get("gender")
        room, notes = request.form.get("room_number"), request.form.get("notes")
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("INSERT INTO users(name, age, gender, room_number, notes) VALUES (?,?,?,?,?)",
                      (name, age, gender, room, notes))
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

# -------------------- 記録 --------------------
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

@app.route("/add_record", methods=["GET", "POST"], endpoint="add_record")
@login_required
def add_record():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name FROM users ORDER BY id")
        users = c.fetchall()
    if request.method == "POST":
        user_id = request.form.get("user_id")
        meal = request.form.get("meal")
        medication = request.form.get("medication")
        toilet = request.form.get("toilet")
        condition = request.form.get("condition")
        memo = request.form.get("memo")
        staff_name = session.get("staff_name")
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO records(user_id, meal, medication, toilet, condition, memo, staff_name)
                VALUES(?,?,?,?,?,?,?)
            """, (user_id, meal, medication, toilet, condition, memo, staff_name))
            conn.commit()
        flash(_("記録を保存しました。"))
        return redirect(url_for("records"))
    return render_template("add_record.html", users=users)

# -------------------- 引継ぎ --------------------
@app.route("/handover", methods=["GET", "POST"])
@login_required
def handover():
    if request.method == "POST":
        h_date = request.form.get("h_date") or date.today().isoformat()
        shift = request.form.get("shift") or "day"
        note = request.form.get("note") or ""
        staff = session.get("staff_name") or ""
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("INSERT INTO handover(h_date, shift, note, staff) VALUES(?,?,?,?)",
                      (h_date, shift, note, staff))
            conn.commit()
        flash(_("引継ぎを追加しました。"))
        return redirect(url_for("handover"))
    today = date.today().isoformat()
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, h_date, shift, note, staff FROM handover WHERE h_date=? ORDER BY id DESC", (today,))
        rows = c.fetchall()
    return render_template("handover.html", rows=rows, today=today)

# -------------------- favicon / 404 --------------------
@app.route("/favicon.ico")
def favicon():
    ico = os.path.join(app.root_path, "static", "favicon.ico")
    if os.path.exists(ico):
        return send_from_directory(os.path.join(app.root_path, "static"), "favicon.ico", mimetype="image/vnd.microsoft.icon")
    return ("", 204)

@app.errorhandler(404)
def not_found(e):
    try:
        return render_template("404.html"), 404
    except Exception:
        return "Not Found", 404

# -------------------- 起動 --------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
