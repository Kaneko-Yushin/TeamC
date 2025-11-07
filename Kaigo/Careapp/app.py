from __future__ import annotations
from flask import (
    Flask, render_template, request, redirect, send_file,
    send_from_directory, session, url_for, flash, jsonify
)
from functools import wraps
import sqlite3, qrcode, io, secrets, os, json, csv, math, re, glob
from datetime import date, datetime
from flask_babel import Babel
from jinja2 import TemplateNotFound

# =========================
# 基本設定
# =========================
APP_ROOT = os.path.dirname(__file__)
DB_PATH = os.environ.get("DB_PATH") or os.path.join(APP_ROOT, "care.db")
APP_SECRET = os.environ.get("APP_SECRET") or os.urandom(16)

app = Flask(__name__)
app.secret_key = APP_SECRET

# =========================
# Babel / i18n（JSON辞書）
# =========================
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
    return redirect(request.referrer or url_for("home"))

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

# =========================
# DB
# =========================
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
        # スタッフ
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
        # 家族向け
        c.execute("""
        CREATE TABLE IF NOT EXISTS family (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE,
          password TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'family'
        )""")
        c.execute("""
        CREATE TABLE IF NOT EXISTS family_map (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          family_name TEXT NOT NULL,
          user_id INTEGER NOT NULL,
          UNIQUE(family_name, user_id)
        )""")
        # 設定（キー/値）
        c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        )""")
        # インデックス
        c.execute("CREATE INDEX IF NOT EXISTS idx_records_user_id ON records(user_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_records_created ON records(created_at DESC)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_handover_date ON handover(h_date, shift)")
        conn.commit()

    # 初回管理者（無ければ作成）
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) AS cnt FROM staff WHERE role='admin'")
        if (c.fetchone()["cnt"] or 0) == 0:
            c.execute(
                "INSERT OR IGNORE INTO staff(name,password,role) VALUES(?,?,?)",
                ("admin", "admin", "admin")
            )
            conn.commit()

# 初期化
init_db()

# 設定ヘルパ
def get_setting(key: str, default: str|None=None) -> str|None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key=?", (key,))
        r = cur.fetchone()
    return (r and r.get("value")) or default

def set_setting(key: str, value: str) -> None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
        INSERT INTO settings(key, value) VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (key, value))
        conn.commit()

def get_int(key: str, default: int) -> int:
    try:
        return int(get_setting(key, str(default)))
    except Exception:
        return default

# =========================
# 認可
# =========================
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
            flash("家族ログインが必要です。")
            return redirect(url_for("family_login"))
        return f(*a, **kw)
    return w

# =========================
# 共通ヘルパ
# =========================
def paginate(total: int, page: int, per_page: int):
    pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, pages))
    return {
        "page": page, "per_page": per_page, "pages": pages, "total": total,
        "has_prev": page > 1, "has_next": page < pages,
        "prev_page": page-1 if page>1 else None, "next_page": page+1 if page<pages else None,
    }

def tpl(name: str, **ctx):
    """テンプレートが無いときは簡易フォールバック"""
    try:
        return render_template(name, **ctx)
    except TemplateNotFound:
        return ctx.get("_fallback_html", "template missing")

# =========================
# 画面：ホーム
# =========================
@app.get("/")
def home():
    return tpl("home.html",
        _fallback_html=(
            "<h1>デジタル介護日誌</h1>"
            "<p><a href='/set_language/ja'>日本語</a> | <a href='/set_language/en'>English</a></p>"
            "<ul>"
            "<li><a href='/staff_login'>スタッフログイン</a></li>"
            "<li><a href='/family_login'>家族ログイン</a></li>"
            "<li><a href='/records'>記録一覧</a>（要ログイン）</li>"
            "<li><a href='/handover'>引継ぎ</a>（要ログイン）</li>"
            "<li><a href='/camera'>見守りカメラ</a>（要ログイン）</li>"
            "<li><a href='/album'>アルバム</a>（要ログイン）</li>"
            "<li><a href='/users'>利用者一覧</a>（管理者）</li>"
            "<li><a href='/admin'>管理</a>（管理者）</li>"
            "</ul>"
        )
    )

# =========================
# スタッフ：登録/ログイン/管理
# =========================
@app.route("/staff_register", methods=["GET","POST"])
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
                          (name,password,role))
                conn.commit()
                flash(_("登録完了。ログインしてください。"))
                return redirect(url_for("staff_login"))
            except sqlite3.IntegrityError:
                flash(_("同名のスタッフがすでに存在します。"))
    return tpl("staff_register.html",
        _fallback_html=(
            "<h2>スタッフ登録</h2>"
            "<form method='post'>"
            "名前:<input name='name' required><br>"
            "パスワード:<input name='password' type='password' required><br>"
            "<button>登録</button>"
            "</form>"
            "<p><a href='/'>ホームへ</a></p>"
        )
    )

@app.route("/staff_login", methods=["GET","POST"])
def staff_login():
    if request.method == "POST":
        name = request.form.get("name")
        password = request.form.get("password")
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT name, role FROM staff WHERE name=? AND password=?", (name,password))
            row = c.fetchone()
        if row:
            session.clear()
            session["staff_name"], session["staff_role"] = row["name"], row["role"]
            flash(_("%(n)s さんでログインしました。", n=row["name"]))
            return redirect(url_for("home"))
        flash(_("名前またはパスワードが間違っています。"))
    return tpl("staff_login.html",
        _fallback_html=(
            "<h2>スタッフログイン</h2>"
            "<form method='post'>"
            "名前:<input name='name' required><br>"
            "パスワード:<input name='password' type='password' required><br>"
            "<button>ログイン</button>"
            "</form>"
            "<p><a href='/staff_register'>スタッフ登録</a> / <a href='/'>ホームへ</a></p>"
        )
    )

@app.get("/logout")
def logout():
    session.clear()
    flash(_("ログアウトしました。"))
    return redirect(url_for("home"))

@app.get("/admin")
@admin_required
def admin_page():
    return tpl("admin.html",
        _fallback_html=(
            "<h2>管理</h2>"
            "<form method='post' action='/admin/staff/add'>"
            "スタッフ名:<input name='name' required> "
            "パスワード:<input name='password' required type='password'> "
            "役割:<select name='role'><option value='caregiver'>caregiver</option>"
            "<option value='admin'>admin</option></select> "
            "<button>登録/更新</button></form>"
            "<p>"
            "<a href='/staff_list'>スタッフ一覧</a> | "
            "<a href='/generate_qr'>QR生成</a> | "
            "<a href='/qr_links'>QRリンク一覧</a> | "
            "<a href='/admin/camera'>見守りカメラ設定</a> | "
            "<a href='/admin/family'>家族アカウント管理</a> | "
            "<a href='/'>ホームへ</a>"
            "</p>"
        )
    )

@app.post("/admin/staff/add")
@admin_required
def admin_staff_add():
    name = (request.form.get("name") or "").strip()
    password = (request.form.get("password") or "").strip()
    role = (request.form.get("role") or "caregiver").strip()
    if not name or not password:
        flash("名前とパスワードを入力してください。")
        return redirect(url_for("admin_page"))
    with get_connection() as conn:
        c = conn.cursor()
        try:
            c.execute("INSERT INTO staff(name, password, role) VALUES (?,?,?)",
                      (name, password, role))
            conn.commit()
            flash(f"スタッフ「{name}」を登録しました（role={role}）。")
        except sqlite3.IntegrityError:
            c.execute("UPDATE staff SET password=?, role=? WHERE name=?",
                      (password, role, name))
            conn.commit()
            flash(f"既存スタッフ「{name}」の情報を更新しました（role={role}）。")
    return redirect(url_for("admin_page"))

@app.get("/staff_list")
@admin_required
def staff_list():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, password, role, login_token FROM staff ORDER BY id")
        staff = c.fetchall()
    return tpl("staff_list.html", staff_list=staff,
        _fallback_html=(
            "<h2>スタッフ一覧</h2>"
            "<table border='1'><tr><th>ID</th><th>名前</th><th>役割</th><th>QR</th><th>削除</th></tr>"
            "{rows}</table><p><a href='/admin'>管理へ</a></p>"
        ).format(rows="".join(
            f"<tr><td>{s['id']}</td><td>{s['name']}</td><td>{s['role']}</td>"
            f"<td>{('あり' if s.get('login_token') else '未発行')}</td>"
            f"<td><a href='/delete_staff/{s['id']}'>削除</a></td></tr>"
            for s in staff
        ))
    )

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
            c.execute("UPDATE staff SET role=?, login_token=? WHERE name=?", (role, token, name))
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
    return tpl("generate_qr.html", names=names,
        _fallback_html=(
            "<h2>QR生成</h2>"
            "<form method='post'>"
            "名前:<select name='name'>{opts}</select> "
            "役割:<select name='role'><option>caregiver</option><option>admin</option></select> "
            "<button>QR作成</button></form>"
            "<p><a href='/admin'>管理へ</a></p>"
        ).format(opts="".join(f"<option>{n}</option>" for n in names))
    )

@app.get("/qr/<token>.png")
@admin_required
def qr_png(token):
    host = request.host.split(":")[0]
    login_url = f"http://{host}:5000/login/{token}"
    img = qrcode.make(login_url)
    buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
    return send_file(buf, mimetype="image/png")

@app.get("/qr_links")
@admin_required
def qr_links():
    host = request.host.split(":")[0]
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT name, login_token FROM staff WHERE login_token IS NOT NULL AND login_token!=''")
        rows = c.fetchall()
    links = [
        f"<li>{r['name']}: <a href='http://{host}:5000/login/{r['login_token']}'>login/{r['login_token']}</a></li>"
        for r in rows
    ] or ["<li>発行なし</li>"]
    return "<h2>QRリンク一覧</h2><ul>" + "".join(links) + "</ul><p><a href='/admin'>管理へ</a></p>"

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

# =========================
# 利用者
# =========================
@app.get("/users")
@admin_required
def users_page():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, age, gender, room_number, notes FROM users ORDER BY id")
        users = c.fetchall()
    return tpl("users.html", users=users,
        _fallback_html=(
            "<h2>利用者一覧</h2>"
            "<p><a href='/add_user'>利用者登録</a> | <a href='/'>ホームへ</a></p>"
            "<table border='1'><tr><th>ID</th><th>氏名</th><th>年齢</th><th>性別</th><th>部屋</th><th>メモ</th><th>削除</th></tr>"
            "{rows}</table>"
        ).format(rows="".join(
            f"<tr><td>{u['id']}</td><td>{u['name']}</td><td>{u.get('age','')}</td>"
            f"<td>{u.get('gender','')}</td><td>{u.get('room_number','')}</td>"
            f"<td>{u.get('notes','')}</td><td><a href='/delete_user/{u['id']}'>削除</a></td></tr>"
            for u in users
        ))
    )

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
    return tpl("add_user.html",
        _fallback_html=(
            "<h2>利用者登録</h2>"
            "<form method='post'>"
            "氏名:<input name='name' required><br>"
            "年齢:<input name='age' type='number' min='0' step='1'><br>"
            "性別:<input name='gender'><br>"
            "部屋:<input name='room_number'><br>"
            "メモ:<textarea name='notes'></textarea><br>"
            "<button>登録</button></form>"
            "<p><a href='/users'>一覧へ</a> | <a href='/'>ホームへ</a></p>"
        )
    )

@app.get("/delete_user/<int:user_id>")
@admin_required
def delete_user(user_id):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
    flash(_("利用者を削除しました。"))
    return redirect(url_for("users_page"))

# =========================
# 記録
# =========================
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
    return tpl("records.html", rows=rows, pg=pg,
        _fallback_html=(
            "<h2>記録一覧</h2>"
            "<p><a href='/add_record'>記録を追加</a> | <a href='/records/export.csv'>CSV出力</a> | <a href='/'>ホームへ</a></p>"
            "<table border='1'><tr><th>ID</th><th>利用者</th><th>食事</th><th>投薬</th>"
            "<th>トイレ</th><th>状態</th><th>メモ</th><th>記録者</th><th>日時</th></tr>"
            "{rows}</table>"
        ).format(rows="".join(
            f"<tr><td>{r['id']}</td><td>{r['user_name']}</td><td>{r.get('meal','')}</td>"
            f"<td>{r.get('medication','')}</td><td>{r.get('toilet','')}</td>"
            f"<td>{r.get('condition','')}</td><td>{r.get('memo','')}</td>"
            f"<td>{r.get('staff_name','')}</td><td>{r.get('created_at','')}</td></tr>"
            for r in rows
        ))
    )

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
    return tpl("add_record.html", users=users,
        _fallback_html=(
            "<h2>記録追加</h2>"
            "<form method='post'>"
            "利用者:<select name='user_id' required>{opts}</select><br>"
            "食事:<input name='meal'><br>"
            "投薬:<input name='medication'><br>"
            "トイレ:<input name='toilet'><br>"
            "状態:<input name='condition'><br>"
            "メモ:<textarea name='memo'></textarea><br>"
            "<button>保存</button></form>"
            "<p><a href='/records'>一覧へ</a> | <a href='/'>ホームへ</a></p>"
        ).format(opts="".join(f"<option value='{u['id']}'>{u['name']}</option>" for u in users))
    )

# =========================
# 引継ぎ
# =========================
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
    return tpl("handover.html", rows=rows, today=h_date, pg=pg,
        _fallback_html=(
            f"<h2>引継ぎ（{h_date}）</h2>"
            "<form method='post'>日付:<input name='h_date' value='{d}'> "
            "勤務:<select name='shift'><option>day</option><option>evening</option><option>night</option></select> "
            "内容:<input name='note' size='60'> <button>追加</button></form>"
            "<table border='1'><tr><th>ID</th><th>日付</th><th>勤務</th><th>内容</th><th>担当</th><th>作成</th></tr>{rows}</table>"
            "<p><a href='/'>ホームへ</a></p>"
        ).format(d=h_date, rows="".join(
            f"<tr><td>{r['id']}</td><td>{r['h_date']}</td><td>{r['shift']}</td>"
            f"<td>{r['note']}</td><td>{r['staff']}</td><td>{r['created_at']}</td></tr>"
            for r in rows
        ))
    )

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

# =========================
# 家族向け（閲覧）
# =========================
@app.route("/family_login", methods=["GET","POST"])
def family_login():
    if request.method == "POST":
        name = request.form.get("name","").strip()
        password = request.form.get("password","").strip()
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
    return tpl("family_login.html",
        _fallback_html=(
            "<h2>家族ログイン</h2>"
            "<form method='post'>"
            "名前:<input name='name' required> "
            "パスワード:<input name='password' type='password' required> "
            "<button>ログイン</button></form>"
            "<p><a href='/'>ホームへ</a></p>"
        )
    )

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
           ORDER BY u.id
        """, (fam,))
        users = c.fetchall()
    return tpl("family_home.html", users=users,
        _fallback_html=(
            "<h2>閲覧可能な利用者</h2>"
            "<ul>{items}</ul><p><a href='/family_logout'>ログアウト</a> | <a href='/'>ホームへ</a></p>"
        ).format(items="".join(
            f"<li><a href='/family/records/{u['id']}'>{u['name']}（{u.get('room_number','')}）</a></li>"
            for u in users
        ))
    )

@app.get("/family/records/<int:user_id>")
@family_login_required
def family_records(user_id):
    fam = session["family_name"]
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT 1 FROM family_map WHERE family_name=? AND user_id=?", (fam, user_id))
        if not c.fetchone():
            return "閲覧権限がありません。", 403
        c.execute("""
          SELECT r.created_at, r.meal, r.medication, r.toilet, r.condition
            FROM records r
           WHERE r.user_id = ?
           ORDER BY r.id DESC
           LIMIT 100
        """, (user_id,))
        rows = c.fetchall()
    return tpl("family_records.html", rows=rows,
        _fallback_html=(
            "<h2>最新記録</h2>"
            "<table border='1'><tr><th>日時</th><th>食事</th><th>投薬</th><th>トイレ</th><th>状態</th></tr>"
            "{rows}</table><p><a href='/family'>戻る</a></p>"
        ).format(rows="".join(
            f"<tr><td>{r['created_at']}</td><td>{r.get('meal','')}</td>"
            f"<td>{r.get('medication','')}</td><td>{r.get('toilet','')}</td>"
            f"<td>{r.get('condition','')}</td></tr>"
            for r in rows
        ))
    )

# =========================
# 家族アカウント管理（管理者専用）
# =========================
@app.get("/admin/family")
@admin_required
def admin_family():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, role FROM family ORDER BY id")
        families = c.fetchall()
        c.execute("SELECT id, name FROM users ORDER BY id")
        users = c.fetchall()
        c.execute("SELECT family_name, user_id FROM family_map ORDER BY id DESC")
        maps = c.fetchall()
    return tpl("admin_family.html", families=families, users=users, maps=maps,
        _fallback_html=(
            "<h2>家族アカウント管理</h2>"
            "<h3>アカウント作成</h3>"
            "<form method='post' action='/admin/family/add'>"
            "名前:<input name='name' required> "
            "パスワード:<input name='password' type='password' required> "
            "<button>作成</button></form>"
            "<h3 class='mt-3'>利用者との紐づけ</h3>"
            "<form method='post' action='/admin/family/map'>家族:"
            "<select name='family_name'>{fopts}</select> 利用者:"
            "<select name='user_id'>{uopts}</select> <button>紐づけ</button></form>"
            "<h4>現在の紐づけ</h4><ul>{maps}</ul>"
            "<p><a href='/admin'>管理へ</a></p>"
        ).format(
            fopts="".join(f"<option>{f['name']}</option>" for f in families) or "<option>(なし)</option>",
            uopts="".join(f"<option value='{u['id']}'>{u['name']}</option>" for u in users) or "<option>(なし)</option>",
            maps="".join(f"<li>{m['family_name']} → user_id {m['user_id']}</li>" for m in maps) or "<li>(なし)</li>"
        )
    )

@app.post("/admin/family/add")
@admin_required
def admin_family_add():
    name = (request.form.get("name") or "").strip()
    password = (request.form.get("password") or "").strip()
    if not name or not password:
        flash("名前・パスワードは必須です。")
        return redirect(url_for("admin_family"))
    with get_connection() as conn:
        c = conn.cursor()
        try:
            c.execute("INSERT INTO family(name, password, role) VALUES(?,?,?)", (name, password, "family"))
            conn.commit()
            flash("家族アカウントを作成しました。")
        except sqlite3.IntegrityError:
            flash("同名の家族アカウントが既にあります。")
    return redirect(url_for("admin_family"))

@app.post("/admin/family/map")
@admin_required
def admin_family_map():
    family_name = (request.form.get("family_name") or "").strip()
    user_id = request.form.get("user_id")
    if not family_name or not user_id:
        flash("家族と利用者を選択してください。")
        return redirect(url_for("admin_family"))
    with get_connection() as conn:
        c = conn.cursor()
        try:
            c.execute("INSERT INTO family_map(family_name, user_id) VALUES(?,?)", (family_name, user_id))
            conn.commit()
            flash("紐づけしました。")
        except sqlite3.IntegrityError:
            flash("すでに紐づけされています。")
    return redirect(url_for("admin_family"))

@app.post("/admin/family/unmap")
@admin_required
def admin_family_unmap():
    family_name = (request.form.get("family_name") or "").strip()
    user_id = request.form.get("user_id")
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM family_map WHERE family_name=? AND user_id=?", (family_name, user_id))
        conn.commit()
    flash("紐づけを解除しました。")
    return redirect(url_for("admin_family"))

@app.post("/admin/family/delete/<int:fid>")
@admin_required
def admin_family_delete(fid):
    with get_connection() as conn:
        c = conn.cursor()
        # 紐づけも一緒に削除
        c.execute("SELECT name FROM family WHERE id=?", (fid,))
        row = c.fetchone()
        if row:
            c.execute("DELETE FROM family_map WHERE family_name=?", (row["name"],))
        c.execute("DELETE FROM family WHERE id=?", (fid,))
        conn.commit()
    flash("家族アカウントを削除しました。")
    return redirect(url_for("admin_family"))

# =========================
# 見守りカメラ / アルバム
# =========================
@app.get("/camera")
@login_required
def camera_page():
    return tpl("camera.html",
        _fallback_html=(
            "<h2>カメラ（簡易アップロード）</h2>"
            "<form method='post' action='/album/upload' enctype='multipart/form-data'>"
            "<input type='file' name='photo' accept='image/png,image/jpeg' required>"
            "<button>アップロード</button></form>"
            "<p>※2MBまで / JPG, PNG</p>"
            "<p><a href='/'>ホームへ</a> | <a href='/album'>アルバム</a></p>"
        )
    )

# 管理：見守りカメラ設定（管理者のみ）
@app.route("/admin/camera", methods=["GET","POST"])
@admin_required
def admin_camera_settings():
    # デフォルト値
    defaults = {
        "camera.mode": "fixed",           # fixed or random
        "camera.interval_sec": "300",     # 固定秒
        "camera.random_min_sec": "120",   # ランダム最小
        "camera.random_max_sec": "600",   # ランダム最大
        "camera.auto_prune_max_files": "500"  # アルバム上限枚数（古い順に削除）
    }
    if request.method == "POST":
        for k in defaults:
            v = (request.form.get(k) or defaults[k]).strip()
            set_setting(k, v)
        flash("見守りカメラ設定を保存しました。")
        return redirect(url_for("admin_camera_settings"))

    # 表示用に現在値を集める
    vals = {k: get_setting(k, defaults[k]) for k in defaults}
    return tpl("admin_camera.html", settings=vals,
        _fallback_html=(
            "<h2>見守りカメラ設定</h2>"
            "<form method='post'>"
            "モード:"
            "<select name='camera.mode'>"
            f"<option value='fixed' {'selected' if vals['camera.mode']=='fixed' else ''}>固定間隔</option>"
            f"<option value='random' {'selected' if vals['camera.mode']=='random' else ''}>ランダム間隔</option>"
            "</select><br>"
            "固定間隔(秒): <input name='camera.interval_sec' type='number' min='10' value='{fi}'><br>"
            "ランダム最小(秒): <input name='camera.random_min_sec' type='number' min='10' value='{rmin}'><br>"
            "ランダム最大(秒): <input name='camera.random_max_sec' type='number' min='10' value='{rmax}'><br>"
            "アルバム上限(枚): <input name='camera.auto_prune_max_files' type='number' min='1' value='{maxf}'><br>"
            "<button>保存</button></form>"
            "<p><a href='/admin'>管理へ</a></p>"
        ).format(
            fi=vals["camera.interval_sec"],
            rmin=vals["camera.random_min_sec"],
            rmax=vals["camera.random_max_sec"],
            maxf=vals["camera.auto_prune_max_files"],
        )
    )

# クライアント向け設定API（フロントJSで参照可）
@app.get("/api/camera/config")
@login_required
def api_camera_config():
    mode = get_setting("camera.mode", "fixed")
    cfg = {
        "mode": mode,
        "interval_sec": get_int("camera.interval_sec", 300),
        "random_min_sec": get_int("camera.random_min_sec", 120),
        "random_max_sec": get_int("camera.random_max_sec", 600),
        "auto_prune_max_files": get_int("camera.auto_prune_max_files", 500),
    }
    return jsonify(cfg)

@app.post("/album/upload")
@login_required
def album_upload():
    f = request.files.get("photo")
    if not f: return "no file", 400
    if f.mimetype not in ("image/jpeg","image/png"): return "bad type", 400
    data = f.read()
    if len(data) > 2 * 1024 * 1024:
        return "too large", 400
    folder = os.path.join(app.root_path, "static", "album")
    os.makedirs(folder, exist_ok=True)
    name = f"cap_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}.jpg"
    path = os.path.join(folder, name)
    with open(path, "wb") as out:
        out.write(data)

    # オート・プリune（設定上限を超えたら古い順に削除）
    max_files = get_int("camera.auto_prune_max_files", 500)
    files = sorted(
        glob.glob(os.path.join(folder, "*.*")),
        key=os.path.getmtime
    )
    if len(files) > max_files:
        for old in files[:len(files)-max_files]:
            try: os.remove(old)
            except Exception: pass

    return "ok", 200

@app.get("/album")
@login_required
def album_index():
    folder = os.path.join(app.root_path, "static", "album")
    os.makedirs(folder, exist_ok=True)
    files = sorted(
        (f for f in os.listdir(folder)
         if f.lower().endswith((".jpg", ".jpeg", ".png"))),
        reverse=True,
    )
    try:
        return render_template("album.html", files=files)
    except TemplateNotFound:
        items = "".join(
            f"<div style='width:160px;display:inline-block;margin:6px;text-align:center'>"
            f"<a href='/static/album/{f}' target='_blank'>"
            f"<img src='/static/album/{f}' style='width:160px;height:120px;object-fit:cover;border-radius:8px'></a>"
            f"<div class='small text-muted' style='word-break:break-all'>{f}</div>"
            f"<form method='post' action='/album/delete' onsubmit=\"return confirm('削除しますか？');\">"
            f"<input type='hidden' name='filename' value='{f}'/>"
            f"<button>削除</button></form>"
            f"</div>"
            for f in files
        ) or "<p>まだありません。</p>"
        return (
            "<div class='container py-3'>"
            "<a class='btn btn-outline-secondary mb-3' href='/'><span>🏠</span> ホームへ</a>"
            "<h3>アルバム</h3>"
            f"{items}"
            "</div>"
        )

@app.post("/album/delete")
@admin_required   # 介護職員にも許可したい場合は @login_required に変更
def album_delete():
    filename = (request.form.get("filename") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._\-]+", filename):
        flash("不正なファイル名です。")
        return redirect(url_for("album_index"))

    folder = os.path.join(app.root_path, "static", "album")
    os.makedirs(folder, exist_ok=True)

    target_path = os.path.abspath(os.path.join(folder, filename))
    if not target_path.startswith(os.path.abspath(folder) + os.sep):
        flash("不正なパスです。")
        return redirect(url_for("album_index"))

    if not os.path.exists(target_path):
        flash("ファイルが見つかりません。")
        return redirect(url_for("album_index"))

    try:
        os.remove(target_path)
        flash("写真を削除しました。")
    except Exception as e:
        flash(f"削除に失敗しました: {e}")
    return redirect(url_for("album_index"))

# =========================
# 雑多
# =========================
@app.get("/favicon.ico")
def favicon():
    ico = os.path.join(app.root_path, "static", "favicon.ico")
    if os.path.exists(ico):
        return send_from_directory(os.path.join(app.root_path, "static"), "favicon.ico", mimetype="image/vnd.microsoft.icon")
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

if __name__ == "__main__":
    # Service Worker は base.html で登録する想定（PWA対応）
    app.run(host="0.0.0.0", port=5000, debug=True)
