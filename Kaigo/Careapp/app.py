from flask import Flask, render_template, request, redirect, send_file, session, url_for, flash
from functools import wraps
import sqlite3, qrcode, io, secrets, os
from datetime import date
# =========================
# 設定
# =========================
app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET", secrets.token_hex(16))
DB_PATH = "care.db"
LANGUAGES = ("ja", "en")

# -------------------------
# 軽量 i18n（Babelなしで即反映）
# -------------------------
TR = {
    "en": {
        # 共通
        "ホーム":"Home","ログイン":"Log in","ログアウト":"Log out","管理ページ":"Admin",
        "利用者一覧":"Users","記録一覧":"Records","引継ぎ":"Handover","戻る":"Back","表示":"Show",
        "保存":"Save","削除":"Delete","本当に削除しますか？":"Are you sure to delete?",
        "ホームへ":"Back to Home","← ホームに戻る":"← Back to Home","＋ 新しい利用者を登録":"+ Add New User",
        "記録を追加":"Add Record","＋ QR発行（新規）":"+ Issue QR (New)","QRリンク":"QR Link","未発行":"Not issued",
        "QR再発行":"Re-issue QR","QR発行":"Issue QR","役職":"Role","名前":"Name","操作":"Actions",
        "管理者":"Admin","スタッフ":"Staff","登録済みスタッフの確認と管理":"Manage registered staff",
        "スタッフ一覧":"Staff List","スタッフ一覧 - デジタル介護日誌":"Staff List - Digital Care Notes",
        "戻る（管理）":"Back (Admin)","admin_page":"Admin Page","login_btn":"Log in",

        # 利用者
        "👥 利用者一覧":"👥 Users","年齢":"Age","性別":"Gender","部屋番号":"Room No.","備考":"Notes",
        "＋ 新しい利用者を登録":"+ Add New User","利用者":"User",

        # 記録
        "記録追加":"Add Record","食事":"Meal","服薬":"Medication","排泄":"Toilet",
        "体調":"Condition","メモ":"Memo","記録者":"Staff","作成日時":"Created At",

        # 引継ぎ
        "引継ぎボード":"Handover Board","日付":"Date","シフト":"Shift","日勤":"Day","遅番":"Evening","夜勤":"Night",
        "対象者":"Resident","優先度":"Priority","タイトル":"Title","内容":"Content","追加":"Add",

        # スタッフ登録/ログイン画面
        "スタッフ登録":"Staff Register","パスワード":"Password",
        "登録":"Register",
        # フラッシュ
        "ログインしました。":"Logged in.",
        "ログインが必要です。":"Login required.",
        "名前またはパスワードが間違っています。":"Invalid name or password.",
        "登録完了。ログインしてください。":"Registration complete. Please log in.",
        "同名のスタッフがすでに存在します。":"Same name already exists.",
        "利用者を登録しました。":"User registered.",
        "利用者を削除しました。":"User deleted.",
        "記録を保存しました。":"Record saved.",
        "引継ぎを追加しました。":"Handover added.",
        "ログアウトしました。":"Logged out.",
        "無効なQRコードです。":"Invalid QR code.",
    }
}
def _(s: str) -> str:
    lang = session.get("lang","ja")
    if lang == "en":
        return TR["en"].get(s, s)
    return s

@app.context_processor
def inject_globals():
    return {"_": _, "current_lang": session.get("lang","ja")}

@app.route("/set_language/<lang>")
def set_language(lang):
    if lang not in LANGUAGES: lang = "ja"
    session["lang"] = lang
    return redirect(request.referrer or url_for("home"))

# =========================
# DBユーティリティ
# =========================
def get_connection():
    return sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)

def ensure_column(c, table, column_def):
    # column_def 例: "room_number TEXT"
    col = column_def.split()[0]
    c.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in c.fetchall()]
    if col not in cols:
        try:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
        except sqlite3.OperationalError:
            pass

def init_db():
    with get_connection() as conn:
        c = conn.cursor()
        # users
        c.execute("""
            CREATE TABLE IF NOT EXISTS users(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT,
              age INTEGER,
              gender TEXT
            )
        """)
        ensure_column(c,"users","room_number TEXT")
        ensure_column(c,"users","notes TEXT")

        # records
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

        # staff
        c.execute("""
            CREATE TABLE IF NOT EXISTS staff(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT UNIQUE,
              password TEXT,
              role TEXT,
              login_token TEXT
            )
        """)

        # handover
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
else:
    init_db()  # 既存DBに不足カラムがあれば追加

# =========================
# 認証系
# =========================
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
            return "❌ admin only", 403
        return f(*args, **kwargs)
    return wrapper

# =========================
# 画面
# =========================
@app.route("/")
def home():
    return render_template("home.html", title="Home")

# --- スタッフ登録 / ログイン / ログアウト
@app.route("/staff_register", methods=["GET","POST"])
def staff_register():
    if request.method == "POST":
        name = request.form.get("name","").strip()
        password = request.form.get("password","").strip()
        role = "caregiver"
        with get_connection() as conn:
            c = conn.cursor()
            try:
                c.execute("INSERT INTO staff(name,password,role) VALUES(?,?,?)", (name,password,role))
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
            c.execute("SELECT name, role FROM staff WHERE name=? AND password=?", (name,password))
            row = c.fetchone()
        if row:
            session["staff_name"] = row[0]
            session["staff_role"] = row[1]
            flash(_("ログインしました。"))
            return redirect(url_for("home"))
        else:
            flash(_("名前またはパスワードが間違っています。"))
    return render_template("staff_login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash(_("ログアウトしました。"))
    return redirect(url_for("home"))

# --- 利用者
@app.route("/users")
@admin_required
def users_page():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id,name,age,gender,room_number,notes FROM users ORDER BY id")
        users = c.fetchall()
    return render_template("users.html", users=users)

@app.route("/add_user", methods=["GET","POST"])
@admin_required
def add_user():
    if request.method == "POST":
        name = request.form.get("name")
        age = request.form.get("age")
        gender = request.form.get("gender")
        room = request.form.get("room_number")
        notes = request.form.get("notes")
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("INSERT INTO users(name,age,gender,room_number,notes) VALUES(?,?,?,?,?)",
                      (name,age,gender,room,notes))
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

# --- 記録
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

@app.route("/add_record", methods=["GET","POST"])
@login_required
def add_record():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id,name FROM users ORDER BY id")
        users = c.fetchall()

    MEAL_CHOICES = ["全量","8割","半分","1/3","ほぼ食べず","その他"]
    MEDICATION_CHOICES = ["済","一部","未","自己管理","その他"]
    TOILET_CHOICES = ["自立","誘導","介助","失禁なし","失禁あり","その他"]
    CONDITION_CHOICES = ["良好","普通","要観察","受診","発熱(37.5℃～)","その他"]

    if request.method == "POST":
        def picked(val, other):
            other = (other or "").strip()
            return other if (val=="その他" and other) else val

        user_id = request.form.get("user_id")
        meal = picked(request.form.get("meal"), request.form.get("meal_other"))
        medication = picked(request.form.get("medication"), request.form.get("medication_other"))
        toilet = picked(request.form.get("toilet"), request.form.get("toilet_other"))
        condition = picked(request.form.get("condition"), request.form.get("condition_other"))
        memo = request.form.get("memo")
        staff_name = session.get("staff_name")

        with get_connection() as conn:
            c = conn.cursor()
            c.execute("""INSERT INTO records(user_id,meal,medication,toilet,condition,memo,staff_name)
                         VALUES(?,?,?,?,?,?,?)""",
                      (user_id,meal,medication,toilet,condition,memo,staff_name))
            conn.commit()
        flash(_("記録を保存しました。"))
        return redirect(url_for("records"))

    return render_template("add_record.html",
        users=users,
        MEAL_CHOICES=MEAL_CHOICES,
        MEDICATION_CHOICES=MEDICATION_CHOICES,
        TOILET_CHOICES=TOILET_CHOICES,
        CONDITION_CHOICES=CONDITION_CHOICES)

# --- 引継ぎ
@app.route("/handover", methods=["GET"])
@login_required
def handover():
    on_date = request.args.get("date") or date.today().isoformat()
    shift = request.args.get("shift") or "day"
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id,name FROM users ORDER BY id")
        residents = c.fetchall()
        c.execute("""
          SELECT h.id,h.on_date,h.shift,u.name,h.priority,h.title,h.body,h.created_at
            FROM handover h LEFT JOIN users u ON h.resident_id = u.id
           WHERE h.on_date=? AND h.shift=?
        ORDER BY h.priority ASC, h.id DESC
        """, (on_date,shift))
        items = c.fetchall()
    return render_template("handover.html", items=items, residents=residents,
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
        c.execute("""INSERT INTO handover(on_date,shift,resident_id,priority,title,body)
                     VALUES(?,?,?,?,?,?)""",
                  (on_date,shift,resident_id,priority,title,body))
        conn.commit()
    flash(_("引継ぎを追加しました。"))
    return redirect(url_for("handover", date=on_date, shift=shift))

# --- 管理者ページ & スタッフ管理 & QR
@app.route("/admin")
@admin_required
def admin_page():
    return render_template("admin.html")

@app.route("/staff_list")
@admin_required
def staff_list():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id,name,password,role,login_token FROM staff ORDER BY id")
        staff = c.fetchall()
    return render_template("staff_list.html", staff_list=staff)

@app.route("/qr_reissue/<name>")
@admin_required
def qr_reissue(name):
    token = secrets.token_hex(8)
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE staff SET login_token=? WHERE name=?", (token,name))
        conn.commit()
    flash("OK")
    return redirect(url_for("staff_list"))

@app.route("/delete_staff/<int:sid>")
@admin_required
def delete_staff(sid):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM staff WHERE id=?", (sid,))
        conn.commit()
    flash("OK")
    return redirect(url_for("staff_list"))

@app.route("/generate_qr", methods=["GET","POST"])
@admin_required
def generate_qr():
    if request.method == "POST":
        name = request.form.get("name")
        role = request.form.get("role") or "caregiver"
        token = secrets.token_hex(8)
        with get_connection() as conn:
            c = conn.cursor()
            # 既存があれば更新、なければ作成
            c.execute("SELECT id FROM staff WHERE name=?", (name,))
            row = c.fetchone()
            if row:
                c.execute("UPDATE staff SET role=?, login_token=? WHERE id=?", (role,token,row[0]))
            else:
                c.execute("INSERT INTO staff(name,password,role,login_token) VALUES(?,?,?,?)",
                          (name,"",role,token))
            conn.commit()
        host = request.host.split(":")[0]
        login_url = f"http://{host}:5000/login/{token}"
        img = qrcode.make(login_url)
        buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
        return send_file(buf, mimetype="image/png")
    return render_template("generate_qr.html")

@app.route("/login/<token>")
def login_by_qr(token):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT name,role FROM staff WHERE login_token=?", (token,))
        staff = c.fetchone()
    if staff:
        session["staff_name"] = staff[0]
        session["staff_role"] = staff[1]
        flash(_("ログインしました。"))
        return redirect(url_for("home"))
    return _("無効なQRコードです。"), 403

# =========================
# 起動
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
