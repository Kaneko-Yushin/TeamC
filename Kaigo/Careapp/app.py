from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from functools import wraps
import sqlite3, os, secrets, io
from datetime import date
import qrcode

app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET", secrets.token_hex(16))
DB_PATH = "care.db"

# =========================
# DB
# =========================
def get_db():
    return sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)

def init_db():
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
          CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, age INTEGER, gender TEXT,
            room_number TEXT, notes TEXT
          )
        """)
        c.execute("""
          CREATE TABLE IF NOT EXISTS records(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            meal TEXT, medication TEXT, toilet TEXT, condition TEXT, memo TEXT,
            staff_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
          )
        """)
        c.execute("""
          CREATE TABLE IF NOT EXISTS staff(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE, password TEXT, role TEXT,
            login_token TEXT
          )
        """)
        c.execute("""
          CREATE TABLE IF NOT EXISTS handover(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            h_date TEXT, shift TEXT, note TEXT, staff TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
          )
        """)
        conn.commit()

def ensure_handover_schema():
    with get_db() as conn:
        c = conn.cursor()
        c.execute("PRAGMA table_info('handover')")
        cols = {r[1] for r in c.fetchall()}
        if not cols:
            # テーブルなければ作成
            c.execute("""
              CREATE TABLE IF NOT EXISTS handover(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                h_date TEXT, shift TEXT, note TEXT, staff TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
              )
            """)
        else:
            # 欠けていたら追加
            if "h_date" not in cols: c.execute("ALTER TABLE handover ADD COLUMN h_date TEXT")
            if "shift"  not in cols: c.execute("ALTER TABLE handover ADD COLUMN shift TEXT")
            if "note"   not in cols: c.execute("ALTER TABLE handover ADD COLUMN note TEXT")
            if "staff"  not in cols: c.execute("ALTER TABLE handover ADD COLUMN staff TEXT")
            if "created_at" not in cols: c.execute("ALTER TABLE handover ADD COLUMN created_at TIMESTAMP")
            # もし旧カラム date があれば移し替え
            c.execute("PRAGMA table_info('handover')")
            cols2 = {r[1] for r in c.fetchall()}
            if "date" in cols2:
                c.execute("UPDATE handover SET h_date = COALESCE(h_date, date)")
        conn.commit()

if not os.path.exists(DB_PATH):
    init_db()
else:
    ensure_handover_schema()

# =========================
# 多言語（超シンプル辞書）
# =========================
LANGS = ("ja", "en")
T = {
    "en": {
        "ホーム": "Home",
        "スタッフログイン": "Staff Login",
        "スタッフ登録": "Staff Register",
        "管理ページ": "Admin",
        "スタッフ一覧": "Staff List",
        "QR発行": "Issue QR",
        "記録一覧": "Records",
        "記録追加": "Add Record",
        "利用者一覧": "Residents",
        "利用者追加": "Add Resident",
        "引継ぎ": "Handover",
        "保存": "Save",
        "追加": "Add",
        "削除": "Delete",
        "戻る": "Back",
        "ホームに戻る": "Back to Home",
        "QRリンク": "QR Link",
        "未発行": "Not issued",
        "管理者": "Admin",
        "スタッフ": "Staff",
        "本当に削除しますか？": "Are you sure you want to delete?",
        "ログイン": "Login",
        "ログアウト": "Logout",
        "記録を保存しました。": "Record saved.",
        "引継ぎを追加しました。": "Handover added.",
        "ログインが必要です。": "Login required.",
        "名前またはパスワードが間違っています。": "Wrong name or password.",
        "利用者を登録しました。": "Resident registered.",
        "利用者を削除しました。": "Resident deleted.",
        "日付": "Date",
        "シフト": "Shift",
        "内容": "Note",
        "担当": "Staff",
        "選択": "Select",
        "食事": "Meal",
        "服薬": "Medication",
        "排泄": "Toilet",
        "体調": "Condition",
        "メモ": "Memo",
        "利用者": "Resident",
        "年齢": "Age",
        "性別": "Gender",
        "部屋番号": "Room",
        "備考": "Notes",
        "登録": "Register",
        "QR再発行": "Re-issue QR"
    }
}
def current_lang():
    return session.get("lang", "ja")

def _(text):
    if current_lang() == "en":
        return T["en"].get(text, text)
    return text

@app.context_processor
def inject_lang():
    return dict(_=_, current_lang=current_lang())

@app.route("/set_language/<lang>")
def set_language(lang):
    if lang not in LANGS:
        lang = "ja"
    session["lang"] = lang
    return redirect(request.headers.get("Referer") or url_for("home"))

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

# =========================
# 画面
# =========================
@app.route("/")
def home():
    return render_template("home.html")

# ---- スタッフ登録/ログイン/ログアウト
@app.route("/staff_register", methods=["GET", "POST"])
def staff_register():
    if request.method == "POST":
        name = request.form.get("name")
        pw   = request.form.get("password")
        role = request.form.get("role", "caregiver")
        with get_db() as conn:
            c = conn.cursor()
            try:
                c.execute("INSERT INTO staff(name,password,role) VALUES(?,?,?)", (name, pw, role))
                conn.commit()
                flash(_("登録"))
                return redirect(url_for("staff_login"))
            except sqlite3.IntegrityError:
                flash("すでに存在します")
    return render_template("staff_register.html")

@app.route("/staff_login", methods=["GET", "POST"])
def staff_login():
    if request.method == "POST":
        name = request.form.get("name")
        pw   = request.form.get("password")
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT name, role FROM staff WHERE name=? AND password=?", (name, pw))
            row = c.fetchone()
        if row:
            session["staff_name"] = row[0]
            session["staff_role"] = row[1]
            return redirect(url_for("home"))
        else:
            flash(_("名前またはパスワードが間違っています。"))
    return render_template("staff_login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

# ---- 管理ページ
@app.route("/admin")
@admin_required
def admin_page():
    return render_template("admin.html")

# ---- スタッフ一覧・QR発行
@app.route("/staff_list")
@admin_required
def staff_list():
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT id,name,password,role,login_token FROM staff ORDER BY id")
        staff = c.fetchall()
    return render_template("staff_list.html", staff_list=staff)

@app.route("/generate_qr", methods=["GET", "POST"])
@admin_required
def generate_qr():
    if request.method == "POST":
        name = request.form.get("name")
        token = secrets.token_urlsafe(24)
        with get_db() as conn:
            c = conn.cursor()
            c.execute("UPDATE staff SET login_token=? WHERE name=?", (token, name))
            conn.commit()
        flash("QRを発行しました")
        return redirect(url_for("staff_list"))
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT name FROM staff ORDER BY name")
        names = [r[0] for r in c.fetchall()]
    return render_template("generate_qr.html", names=names)

@app.route("/qr_png/<token>")
def qr_png(token):
    # QR画像返却
    img = qrcode.make(url_for("login_by_qr", token=token, _external=True))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

@app.route("/login_by_qr/<token>")
def login_by_qr(token):
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT name, role FROM staff WHERE login_token=?", (token,))
        row = c.fetchone()
    if row:
        session["staff_name"] = row[0]
        session["staff_role"] = row[1]
        return redirect(url_for("home"))
    flash("無効なQRです")
    return redirect(url_for("staff_login"))

@app.route("/delete_staff/<int:sid>")
@admin_required
def delete_staff(sid):
    with get_db() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM staff WHERE id=?", (sid,))
        conn.commit()
    return redirect(url_for("staff_list"))

# ---- 利用者
@app.route("/users")
@admin_required
def users_page():
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT id,name,age,gender,room_number,notes FROM users ORDER BY id")
        users = c.fetchall()
    return render_template("users.html", users=users)

@app.route("/add_user", methods=["GET", "POST"])
@admin_required
def add_user():
    if request.method == "POST":
        name = request.form.get("name")
        age = request.form.get("age")
        gender = request.form.get("gender")
        room = request.form.get("room_number")
        notes = request.form.get("notes")
        with get_db() as conn:
            c = conn.cursor()
            c.execute("INSERT INTO users(name,age,gender,room_number,notes) VALUES(?,?,?,?,?)",
                      (name, age, gender, room, notes))
            conn.commit()
        flash(_("利用者を登録しました。"))
        return redirect(url_for("users_page"))
    return render_template("add_user.html")

@app.route("/delete_user/<int:user_id>")
@admin_required
def delete_user(user_id):
    with get_db() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
    flash(_("利用者を削除しました。"))
    return redirect(url_for("users_page"))

# ---- 記録
@app.route("/records")
@login_required
def records():
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""SELECT r.id, u.name, r.meal, r.medication, r.toilet, r.condition, r.memo, r.staff_name, r.created_at
                     FROM records r JOIN users u ON r.user_id = u.id
                     ORDER BY r.id DESC""")
        rows = c.fetchall()
    return render_template("records.html", rows=rows)

@app.route("/add_record", methods=["GET", "POST"])
@login_required
def add_record():
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT id,name FROM users ORDER BY id")
        users = c.fetchall()
    if request.method == "POST":
        user_id   = request.form.get("user_id")
        meal      = request.form.get("meal")
        medication= request.form.get("medication")
        toilet    = request.form.get("toilet")
        condition = request.form.get("condition")
        memo      = request.form.get("memo")
        staff     = session.get("staff_name")
        with get_db() as conn:
            c = conn.cursor()
            c.execute("""INSERT INTO records(user_id,meal,medication,toilet,condition,memo,staff_name)
                         VALUES(?,?,?,?,?,?,?)""",
                      (user_id, meal, medication, toilet, condition, memo, staff))
            conn.commit()
        flash(_("記録を保存しました。"))
        return redirect(url_for("records"))
    return render_template("add_record.html", users=users)

# ---- 引継ぎ
@app.route("/handover", methods=["GET", "POST"])
@login_required
def handover():
    ensure_handover_schema()
    with get_db() as conn:
        c = conn.cursor()
        if request.method == "POST":
            h_date = request.form.get("h_date") or date.today().isoformat()
            shift  = request.form.get("shift")
            note   = request.form.get("note")
            staff  = request.form.get("staff")
            c.execute("INSERT INTO handover(h_date,shift,note,staff) VALUES(?,?,?,?)",
                      (h_date, shift, note, staff))
            conn.commit()
            flash(_("引継ぎを追加しました。"))
            return redirect(url_for("handover"))
        today = date.today().isoformat()
        c.execute("SELECT id,h_date,shift,note,staff FROM handover WHERE h_date=? ORDER BY id DESC", (today,))
        rows = c.fetchall()
    return render_template("handover.html", rows=rows, today=today)

# =========================
# main
# =========================
if __name__ == "__main__":
    init_db()
    ensure_handover_schema()
    app.run(host="0.0.0.0", port=5000, debug=True)
