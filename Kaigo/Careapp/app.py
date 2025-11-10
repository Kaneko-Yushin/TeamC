from __future__ import annotations

from flask import (
    Flask, render_template, request, redirect, send_file, send_from_directory,
    session, url_for, flash, jsonify
)
from functools import wraps
import sqlite3, qrcode, io, secrets, os, json, csv, math
from datetime import date, datetime, timedelta
from flask_babel import Babel

# ===============================
# 基本設定
# ===============================
APP_ROOT = os.path.dirname(__file__)
DB_PATH = os.environ.get("DB_PATH") or os.path.join(APP_ROOT, "care.db")
APP_SECRET = os.environ.get("APP_SECRET") or os.urandom(16)

app = Flask(__name__)
app.secret_key = APP_SECRET

# セッション維持（言語設定などを持続させる）
@app.before_request
def _make_session_permanent():
    session.permanent = True
    app.permanent_session_lifetime = timedelta(days=30)

# Jinja で now() を使えるように
@app.context_processor
def inject_now():
    return {"now": datetime.now}

# ===============================
# i18n（JSON辞書）
# ===============================
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

def _load_json_translations():
    base = APP_ROOT
    candidates = [
        lambda lang: os.path.join(base, "translations", f"{lang}.json"),
        lambda lang: os.path.join(base, f"{lang}.json"),
    ]
    data = {}
    for lang in app.config["LANGUAGES"]:
        loaded = {}
        for fn in candidates:
            p = fn(lang)
            if os.path.exists(p):
                try:
                    with open(p, encoding="utf-8") as f:
                        loaded = json.load(f)
                except Exception as e:
                    print(f"[i18n] load fail {p}: {e}")
                    loaded = {}
                break
        data[lang] = loaded
    return data

TRANSLATIONS = _load_json_translations()

def _t(key, **kwargs):
    s = TRANSLATIONS.get(get_locale(), {}).get(key, key)
    if kwargs:
        try:
            s = s % kwargs
        except Exception:
            pass
    return s

_ = _t
app.jinja_env.globals.update(_=_, get_locale=get_locale)

@app.get("/set_language/<lang>")
def set_language(lang):
    lang = (lang or "ja").lower()
    if lang in app.config["LANGUAGES"]:
        session["lang"] = lang
        flash(_("言語を切り替えました。"))
    next_url = request.args.get("next") or request.referrer or url_for("home")
    return redirect(next_url)

@app.get("/i18n/reload")
def i18n_reload():
    global TRANSLATIONS
    TRANSLATIONS = _load_json_translations()
    flash(_("言語を切り替えました。"))
    return redirect(request.referrer or url_for("home"))

@app.get("/i18n/debug")
def i18n_debug():
    lang = get_locale()
    return {"current_lang": lang, "keys_loaded": len(TRANSLATIONS.get(lang, {}))}

# ===============================
# DB
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
        # 利用者
        c.execute("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL, age INTEGER, gender TEXT,
          room_number TEXT, notes TEXT
        )""")
        # 職員
        c.execute("""
        CREATE TABLE IF NOT EXISTS staff(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE,
          password TEXT NOT NULL,
          role TEXT NOT NULL,
          login_token TEXT
        )""")
        # 記録
        c.execute("""
        CREATE TABLE IF NOT EXISTS records(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER NOT NULL,
          meal TEXT, medication TEXT, toilet TEXT, condition TEXT, memo TEXT,
          staff_name TEXT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )""")
        # 引継ぎ
        c.execute("""
        CREATE TABLE IF NOT EXISTS handover(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          h_date TEXT NOT NULL,
          shift TEXT NOT NULL,
          note TEXT NOT NULL,
          staff TEXT NOT NULL,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        # 家族アカウント
        c.execute("""
        CREATE TABLE IF NOT EXISTS family(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE,
          password TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'family'
        )""")
        # 家族と利用者の紐付け
        c.execute("""
        CREATE TABLE IF NOT EXISTS family_map(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          family_name TEXT NOT NULL,
          user_id INTEGER NOT NULL,
          UNIQUE(family_name, user_id)
        )""")
        # Index
        c.execute("CREATE INDEX IF NOT EXISTS idx_records_user_id ON records(user_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_records_created ON records(created_at DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_handover_date ON handover(h_date, shift)")
        conn.commit()

    # 初回管理者自動作成
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) AS cnt FROM staff WHERE role='admin'")
        if (c.fetchone()["cnt"] or 0) == 0:
            c.execute("INSERT OR IGNORE INTO staff(name,password,role) VALUES(?,?,?)",
                      ("admin", "admin", "admin"))
            conn.commit()

init_db()

# ===============================
# 認可
# ===============================
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

def family_login_required(f):
    @wraps(f)
    def w(*a, **kw):
        if session.get("family_name") is None:
            flash(_("家族ログインが必要です。"))
            return redirect(url_for("family_login"))
        return f(*a, **kw)
    return w

# ===============================
# 共通
# ===============================
def paginate(total: int, page: int, per_page: int):
    pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, pages))
    return {
        "page": page, "per_page": per_page, "pages": pages, "total": total,
        "has_prev": page > 1, "has_next": page < pages,
        "prev_page": page-1 if page>1 else None, "next_page": page+1 if page<pages else None,
    }

# ===============================
# ホーム
# ===============================
@app.get("/")
def home():
    try:
        return render_template("home.html")
    except Exception:
        # テンプレが無くても最低限動く簡易ホーム
        return (
            "<h1>デジタル介護日誌</h1>"
            "<p><a href='/staff_login'>スタッフログイン</a> | "
            "<a href='/family_login'>家族ログイン</a> | "
            "<a href='/records'>記録</a> | "
            "<a href='/handover'>引継ぎ</a> | "
            "<a href='/users'>利用者</a></p>"
        )

# ===============================
# 職員：登録/ログイン/管理
# ===============================
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
                c.execute("INSERT INTO staff(name,password,role) VALUES (?,?,?)",
                          (name, password, role))
                conn.commit()
                flash(_("登録完了。ログインしてください。"))
                return redirect(url_for("staff_login"))
            except sqlite3.IntegrityError:
                flash(_("同名のスタッフがすでに存在します。"))
    return render_template("staff_register.html")

@app.route("/staff_login", methods=["GET","POST"])
def staff_login():
    if request.method == "POST":
        name = request.form.get("name")
        password = request.form.get("password")
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT name, role FROM staff WHERE name=? AND password=?",
                      (name, password))
            row = c.fetchone()
        if row:
            session.clear()
            session["staff_name"], session["staff_role"] = row["name"], row["role"]
            flash(_("%(n)s さんでログインしました。", n=row["name"]))
            return redirect(url_for("home"))
        flash(_("名前またはパスワードが間違っています。"))
    return render_template("staff_login.html")

@app.get("/logout")
def logout():
    session.clear()
    flash(_("ログアウトしました。"))
    return redirect(url_for("home"))

@app.get("/admin")
@admin_required
def admin_page():
    return render_template("admin.html")

@app.post("/admin/staff/add")
@admin_required
def admin_staff_add():
    name = (request.form.get("name") or "").strip()
    password = (request.form.get("password") or "").strip()
    role = (request.form.get("role") or "caregiver").strip()
    if not name or not password:
        flash(_("名前とパスワードを入力してください。"))
        return redirect(url_for("admin_page"))
    with get_connection() as conn:
        c = conn.cursor()
        try:
            c.execute("INSERT INTO staff(name,password,role) VALUES(?,?,?)",
                      (name, password, role))
            conn.commit()
            flash(_("スタッフ「%(n)s」を登録しました（role=%(r)s）。", n=name, r=role))
        except sqlite3.IntegrityError:
            c.execute("UPDATE staff SET password=?, role=? WHERE name=?",
                      (password, role, name))
            conn.commit()
            flash(_("既存スタッフ「%(n)s」を更新しました（role=%(r)s）。", n=name, r=role))
    return redirect(url_for("admin_page"))

@app.get("/staff_list")
@admin_required
def staff_list():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, password, role, login_token FROM staff ORDER BY id")
        staff = c.fetchall()
    return render_template("staff_list.html", staff_list=staff)

@app.route("/delete_staff/<int:sid>", methods=["POST","GET"])
@admin_required
def delete_staff(sid):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM staff WHERE id=?", (sid,))
        conn.commit()
    flash(_("スタッフを削除しました。"))
    return redirect(url_for("staff_list"))

@app.route("/generate_qr", methods=["GET","POST"])
@admin_required
def generate_qr():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        role = (request.form.get("role") or "caregiver").strip()
        token = secrets.token_hex(8)
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("UPDATE staff SET role=?, login_token=? WHERE name=?",
                      (role, token, name))
            if c.rowcount == 0:
                c.execute("INSERT INTO staff(name, role, password, login_token) VALUES(?,?,?,?)",
                          (name, role, "pass", token))
            conn.commit()
        host = request.host.split(":")[0]
        login_url = f"http://{host}:5000/login/{token}"
        img = qrcode.make(login_url)
        buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
        return send_file(buf, mimetype="image/png")
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT name FROM staff ORDER BY id")
        names = [r["name"] for r in c.fetchall()]
    return render_template("generate_qr.html", names=names)

@app.get("/qr/<token>.png")
@admin_required
def qr_png(token):
    host = request.host.split(":")[0]
    login_url = f"http://{host}:5000/login/{token}"
    img = qrcode.make(login_url)
    buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
    return send_file(buf, mimetype="image/png")

@app.get("/login/<token>")
def login_by_qr(token):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT name, role FROM staff WHERE login_token=?", (token,))
        row = c.fetchone()
    if not row:
        return _("無効なQRコードです。"), 403
    session.clear()
    session["staff_name"], session["staff_role"] = row["name"], row["role"]
    flash(_("%(n)s さんでログインしました。", n=row["name"]))
    return redirect(url_for("home"))

# ===============================
# 利用者
# ===============================
@app.get("/users")
@admin_required
def users_page():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, age, gender, room_number, notes FROM users ORDER BY id")
        users = c.fetchall()
    return render_template("users.html", users=users)

@app.route("/add_user", methods=["GET","POST"])
@admin_required
def add_user():
    if request.method == "POST":
        name  = request.form.get("name")
        age   = request.form.get("age")
        gender= request.form.get("gender")
        room  = request.form.get("room_number")
        notes = request.form.get("notes")
        with get_connection() as conn:
            c = conn.cursor()
            c.execute(
                "INSERT INTO users(name, age, gender, room_number, notes) VALUES (?,?,?,?,?)",
                (name, age, gender, room, notes)
            )
            conn.commit()
        flash(_("利用者を登録しました。"))
        return redirect(url_for("users_page"))
    return render_template("add_user.html")

@app.get("/delete_user/<int:user_id>")
@admin_required
def delete_user(user_id):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
    flash(_("利用者を削除しました。"))
    return redirect(url_for("users_page"))

# ===============================
# 記録
# ===============================
@app.get("/records")
@login_required
def records():
    page = int(request.args.get("page", 1))
    per_page = max(1, min(int(request.args.get("per_page", 20)), 100))
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) AS cnt FROM records")
        total = c.fetchone()["cnt"]
        pg = paginate(total, page, per_page)
        offset = (pg["page"] - 1) * pg["per_page"]
        c.execute("""
        SELECT r.id, u.name AS user_name, r.meal, r.medication, r.toilet, r.condition,
               r.memo, r.staff_name, r.created_at
          FROM records r JOIN users u ON r.user_id = u.id
         ORDER BY r.id DESC
         LIMIT ? OFFSET ?
        """, (pg["per_page"], offset))
        rows = c.fetchall()
    return render_template("records.html", rows=rows, pg=pg)

@app.get("/records/export.csv")
@admin_required
def export_records_csv():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
        SELECT r.id, u.name AS user_name, r.meal, r.medication, r.toilet, r.condition,
               r.memo, r.staff_name, r.created_at
          FROM records r JOIN users u ON r.user_id = u.id
         ORDER BY r.id DESC
        """)
    rows = c.fetchall()
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=[
        "id","user_name","meal","medication","toilet","condition","memo","staff_name","created_at"
    ])
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    mem = io.BytesIO(buf.getvalue().encode("utf-8-sig"))
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return send_file(mem, as_attachment=True,
                     download_name=f"records_{ts}.csv", mimetype="text/csv")

@app.get("/api/records")
@login_required
def api_records():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
        SELECT r.id, u.name AS user_name, r.meal, r.medication, r.toilet, r.condition,
               r.memo, r.staff_name, r.created_at
          FROM records r JOIN users u ON r.user_id = u.id
         ORDER BY r.id DESC LIMIT 200
        """)
        rows = c.fetchall()
    return jsonify({"records": rows})

@app.route("/add_record", methods=["GET","POST"])
@login_required
def add_record():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name FROM users ORDER BY id")
        users = c.fetchall()
    if request.method == "POST":
        user_id    = request.form.get("user_id")
        meal       = request.form.get("meal")
        medication = request.form.get("medication")
        toilet     = request.form.get("toilet")
        condition  = request.form.get("condition")
        memo       = request.form.get("memo")
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

# ===============================
# 引継ぎ
# ===============================
@app.route("/handover", methods=["GET","POST"])
@login_required
def handover():
    if request.method == "POST":
        h_date = request.form.get("h_date") or date.today().isoformat()
        shift  = request.form.get("shift") or "day"
        note   = request.form.get("note") or ""
        staff  = session.get("staff_name") or ""
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("INSERT INTO handover(h_date, shift, note, staff) VALUES(?,?,?,?)",
                      (h_date, shift, note, staff))
            conn.commit()
        flash(_("引継ぎを追加しました。"))
        return redirect(url_for("handover"))
    h_date = request.args.get("date") or date.today().isoformat()
    page = int(request.args.get("page", 1))
    per_page = max(1, min(int(request.args.get("per_page", 50)), 200))
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) AS cnt FROM handover WHERE h_date=?", (h_date,))
        total = c.fetchone()["cnt"]
        pg = paginate(total, page, per_page)
        offset = (pg["page"] - 1) * pg["per_page"]
        c.execute("""
        SELECT id, h_date, shift, note, staff, created_at
          FROM handover
         WHERE h_date = ?
         ORDER BY id DESC
         LIMIT ? OFFSET ?
        """, (h_date, pg["per_page"], offset))
        rows = c.fetchall()
    return render_template("handover.html", rows=rows, today=h_date, pg=pg)

@app.get("/api/handover")
@login_required
def api_handover():
    h_date = request.args.get("date") or date.today().isoformat()
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
        SELECT id, h_date, shift, note, staff, created_at
          FROM handover
         WHERE h_date = ?
         ORDER BY id DESC
         LIMIT 300
        """, (h_date,))
        rows = c.fetchall()
    return jsonify({"handover": rows})

# ===============================
# 家族向け（ログイン＆閲覧）
# ===============================
@app.route("/family_login", methods=["GET","POST"])
def family_login():
    if request.method == "POST":
        name = request.form.get("name","").strip()
        password = request.form.get("password","").strip()
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT name FROM family WHERE name=? AND password=?",
                      (name, password))
            row = c.fetchone()
        if row:
            session.clear()
            session["family_name"] = row["name"]
            flash(_("%(n)s さんで家族ログインしました。", n=row["name"]))
            return redirect(url_for("family_home"))
        flash(_("名前またはパスワードが間違っています。"))
    return render_template("family_login.html")

@app.get("/family_logout")
def family_logout():
    session.pop("family_name", None)
    flash(_("家族ログアウトしました。"))
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
           ORDER BY u.id
        """, (fam,))
        users = c.fetchall()
    return render_template("family_home.html", users=users)

@app.get("/family/records/<int:user_id>")
@family_login_required
def family_records(user_id):
    fam = session["family_name"]
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM family_map WHERE family_name=? AND user_id=?",
                  (fam, user_id))
        if not c.fetchone():
            return _("閲覧権限がありません。"), 403
        c.execute("""
          SELECT r.created_at, r.meal, r.medication, r.toilet, r.condition
            FROM records r
           WHERE r.user_id = ?
           ORDER BY r.id DESC
           LIMIT 100
        """, (user_id,))
        rows = c.fetchall()
    return render_template("family_records.html", rows=rows)

# ===============================
# 家族アカウント管理（管理者）
# ===============================
@app.get("/admin/family")
@admin_required
def admin_family():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name FROM family ORDER BY id")
        families = c.fetchall()
        c.execute("SELECT id, name FROM users ORDER BY id")
        users = c.fetchall()
        c.execute("SELECT family_name, user_id FROM family_map ORDER BY id DESC")
        maps = c.fetchall()
    return render_template("admin_family.html", families=families, users=users, maps=maps)

@app.post("/admin/family/add")
@admin_required
def admin_family_add():
    name = (request.form.get("name") or "").strip()
    password = (request.form.get("password") or "").strip()
    if not name or not password:
        flash(_("名前とパスワードを入力してください。"))
        return redirect(url_for("admin_family"))
    with get_connection() as conn:
        c = conn.cursor()
        try:
            c.execute("INSERT INTO family(name,password,role) VALUES(?,?,?)",
                      (name, password, "family"))
            conn.commit()
            flash(_("家族アカウント「%(n)s」を作成しました。", n=name))
        except sqlite3.IntegrityError:
            flash(_("同名の家族アカウントが存在します。"))
    return redirect(url_for("admin_family"))

@app.post("/admin/family/delete/<int:fid>")
@admin_required
def admin_family_delete(fid):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT name FROM family WHERE id=?", (fid,))
        row = c.fetchone()
        if row:
            name = row["name"]
            c.execute("DELETE FROM family WHERE id=?", (fid,))
            c.execute("DELETE FROM family_map WHERE family_name=?", (name,))
            conn.commit()
            flash(_("家族アカウント「%(n)s」を削除しました。", n=name))
    return redirect(url_for("admin_family"))

@app.post("/admin/family/map")
@admin_required
def admin_family_map():
    family_name = request.form.get("family_name")
    user_id = request.form.get("user_id")
    if not family_name or not user_id:
        flash(_("家族名と利用者を選択してください。"))
        return redirect(url_for("admin_family"))
    with get_connection() as conn:
        c = conn.cursor()
        try:
            c.execute("INSERT INTO family_map(family_name,user_id) VALUES(?,?)",
                      (family_name, user_id))
            conn.commit()
            flash(_("紐づけました。"))
        except sqlite3.IntegrityError:
            flash(_("すでに紐づけ済みです。"))
    return redirect(url_for("admin_family"))

@app.post("/admin/family/unmap")
@admin_required
def admin_family_unmap():
    family_name = request.form.get("family_name")
    user_id = request.form.get("user_id")
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM family_map WHERE family_name=? AND user_id=?",
                  (family_name, user_id))
        conn.commit()
    flash(_("紐づけを解除しました。"))
    return redirect(url_for("admin_family"))

# ===============================
# 見守りカメラ / アルバム（管理者のみ）
# ===============================
@app.get("/camera")
@admin_required
def camera_page():
    return render_template("camera.html")

@app.get("/album")
@admin_required
def album_index():
    folder = os.path.join(app.root_path, "static", "album")
    os.makedirs(folder, exist_ok=True)
    files = []
    for fn in sorted(os.listdir(folder), reverse=True):
        if fn.lower().endswith((".jpg", ".jpeg", ".png")):
            files.append(fn)
    return render_template("album.html", files=files)

@app.post("/album/upload")
@admin_required
def album_upload():
    f = request.files.get("photo")
    if not f:
        return "no file", 400
    if f.mimetype not in ("image/jpeg", "image/png"):
        return "bad type", 400
    data = f.read()
    if len(data) > 2 * 1024 * 1024:
        return "too large", 400
    folder = os.path.join(app.root_path, "static", "album")
    os.makedirs(folder, exist_ok=True)
    name = f"cap_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}.jpg"
    with open(os.path.join(folder, name), "wb") as out:
        out.write(data)
    return "ok", 200

@app.post("/album/delete/<path:filename>")
@admin_required
def album_delete(filename):
    folder = os.path.join(app.root_path, "static", "album")
    target = os.path.abspath(os.path.join(folder, filename))
    base = os.path.abspath(folder)
    if not target.startswith(base):
        return "bad path", 400
    if os.path.exists(target):
        os.remove(target)
        flash(_("写真を削除しました。"))
    return redirect(url_for("album_index"))

# ===============================
# 雑多
# ===============================
@app.get("/favicon.ico")
def favicon():
    ico = os.path.join(app.root_path, "static", "favicon.ico")
    if os.path.exists(ico):
        return send_from_directory(os.path.join(app.root_path, "static"),
                                   "favicon.ico", mimetype="image/vnd.microsoft.icon")
    return ("", 204)

@app.get("/healthz")
def healthz():
    try:
        with get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return {"ok": True, "db": "up", "time": datetime.now().isoformat()}
    except Exception as e:
        return {"ok": False, "db": "down", "error": str(e)}, 500

@app.errorhandler(404)
def not_found(e):
    try:
        return render_template("404.html"), 404
    except Exception:
        return "Not Found", 404

# ===============================
# 起動
# ===============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
