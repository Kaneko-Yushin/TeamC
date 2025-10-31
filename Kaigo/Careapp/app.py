# app.py  ――― 全部入り・単体完結版
from flask import Flask, render_template, request, redirect, send_file, session, url_for, flash, Response
from functools import wraps
import sqlite3
import qrcode
import io
import secrets
import os
from datetime import date

app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET", secrets.token_hex(16))
DB_PATH = "care.db"

# ------------------------------------------------------------
# DB 接続ユーティリティ
# ------------------------------------------------------------
def get_db():
    return sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)

def init_db():
    with get_db() as conn:
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

        # 引継ぎ（シンプル版）
        c.execute("""
          CREATE TABLE IF NOT EXISTS handover(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            h_date TEXT,          -- YYYY-MM-DD
            shift TEXT,           -- 例: 早/日/遅/夜
            note TEXT,            -- 申送り
            staff TEXT,           -- 記入者
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
          )
        """)

        conn.commit()

if not os.path.exists(DB_PATH):
    init_db()

# ------------------------------------------------------------
# 多言語（超軽量・Babelなし）
# ------------------------------------------------------------
LANGS = ("ja", "en")
# キーは“日本語UIで使っている文字列またはキー名”にしておく
T = {
    "en": {
        "ホーム": "Home",
        "記録一覧": "Records",
        "記録追加": "Add Record",
        "利用者一覧": "Residents",
        "引継ぎ": "Handover",
        "管理ページ": "Admin",
        "スタッフ一覧": "Staff List",
        "スタッフ登録": "Register",
        "ログイン": "Login",
        "ログアウト": "Logout",
        "＋ 新しい利用者を登録": "+ Add new resident",
        "← ホームに戻る": "← Back to Home",
        "年齢": "Age",
        "性別": "Gender",
        "部屋番号": "Room",
        "備考": "Notes",
        "削除": "Delete",
        "本当に削除しますか？": "Are you sure you want to delete?",
        "＋ QR発行（新規）": "+ Issue QR (new)",
        "← 管理ページに戻る": "← Back to Admin",
        "QRリンク": "QR link",
        "QR再発行": "Reissue QR",
        "未発行": "Not issued",
        "保存": "Save",
        "食事": "Meal",
        "服薬": "Medication",
        "排泄": "Toilet",
        "体調": "Condition",
        "メモ": "Memo",
        "ログインが必要です。": "Login required.",
        "管理者権限が必要です。": "Admin privilege required.",
        "ログインしました。": "Logged in.",
        "名前またはパスワードが間違っています。": "Incorrect name or password.",
        "利用者を登録しました。": "Resident added.",
        "利用者を削除しました。": "Resident deleted.",
        "記録を保存しました。": "Record saved.",
        "引継ぎを追加しました。": "Handover added.",
        # add_record選択肢
        "全量": "All",
        "8割": "80%",
        "半分": "Half",
        "1/3": "One-third",
        "ほぼ食べず": "Barely ate",
        "その他": "Other",
        "済": "Done",
        "一部": "Partial",
        "未": "Not taken",
        "自己管理": "Self-managed",
        "自立": "Independent",
        "誘導": "Prompted",
        "介助": "Assisted",
        "失禁なし": "No incontinence",
        "失禁あり": "With incontinence",
        "良好": "Good",
        "普通": "Normal",
        "要観察": "Watch",
        "受診": "Doctor visit",
        "発熱(37.5℃～)": "Fever (>=37.5℃)",
        # ボタンなど
        "追加": "Add",
        "ホームに戻る": "Back to Home",
    }
}

def current_lang():
    return session.get("lang", "ja")

def _(text: str) -> str:
    lang = current_lang()
    if lang == "en":
        return T["en"].get(text, T["en"].get(text.strip(), text))
    return text

@app.context_processor
def inject_i18n():
    return dict(_=_, current_lang=current_lang())

@app.route("/set_language/<lang>")
def set_language(lang):
    if lang not in LANGS:
        lang = "ja"
    session["lang"] = lang
    # 直前のページへ戻す
    ref = request.headers.get("Referer")
    return redirect(ref or url_for("home"))

# ------------------------------------------------------------
# 認証系デコレータ
# ------------------------------------------------------------
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

# ------------------------------------------------------------
# ホーム
# ------------------------------------------------------------
@app.route("/")
def home():
    return render_template("home.html")

# ------------------------------------------------------------
# スタッフ登録・ログイン・ログアウト
# ------------------------------------------------------------
@app.route("/staff_register", methods=["GET", "POST"])
def staff_register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "").strip()
        role = request.form.get("role") or "caregiver"
        if not name or not password:
            flash("name/password required")
            return redirect(url_for("staff_register"))
        with get_db() as conn:
            c = conn.cursor()
            try:
                c.execute("INSERT INTO staff(name,password,role) VALUES(?,?,?)", (name, password, role))
                conn.commit()
                flash("registered")
                return redirect(url_for("staff_login"))
            except sqlite3.IntegrityError:
                flash("duplicate name")
    return render_template("staff_register.html")

@app.route("/staff_login", methods=["GET", "POST"])
def staff_login():
    if request.method == "POST":
        name = request.form.get("name")
        password = request.form.get("password")
        with get_db() as conn:
            c = conn.cursor()
            c.execute("SELECT name, role FROM staff WHERE name=? AND password=?", (name, password))
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
    return redirect(url_for("home"))

# ------------------------------------------------------------
# 管理ページ
# ------------------------------------------------------------
@app.route("/admin")
@admin_required
def admin_page():
    return render_template("admin.html", staff_name=session.get("staff_name"))

# 管理ページの別名エンドポイント（テンプレ対応）
app.add_url_rule("/admin", endpoint="staff_admin_bp.admin_page", view_func=admin_page)

# ------------------------------------------------------------
# スタッフ一覧 / QR
# ------------------------------------------------------------
@app.route("/staff_list")
@admin_required
def staff_list():
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, password, role, login_token FROM staff ORDER BY id")
        staff = c.fetchall()
    return render_template("staff_list.html", staff_list=staff)

@app.route("/delete_staff/<int:sid>")
@admin_required
def delete_staff(sid):
    with get_db() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM staff WHERE id=?", (sid,))
        conn.commit()
    flash("deleted")
    return redirect(url_for("staff_list"))

@app.route("/qr_reissue/<name>")
@admin_required
def qr_reissue(name):
    token = secrets.token_hex(8)
    with get_db() as conn:
        c = conn.cursor()
        c.execute("UPDATE staff SET login_token=? WHERE name=?", (token, name))
        conn.commit()
    flash("QR reissued")
    return redirect(url_for("staff_list"))

@app.route("/generate_qr", methods=["GET", "POST"])
@admin_required
def generate_qr():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        role = request.form.get("role") or "caregiver"
        token = secrets.token_hex(8)
        with get_db() as conn:
            c = conn.cursor()
            # すでに存在する場合は上書き
            c.execute("""
              INSERT INTO staff(name, role, login_token) VALUES(?,?,?)
              ON CONFLICT(name) DO UPDATE SET role=excluded.role, login_token=excluded.login_token
            """, (name, role, token))
            conn.commit()
        # QRに埋め込むURL
        host = request.host.split(":")[0]
        login_url = f"http://{host}:5000/login/{token}"
        img = qrcode.make(login_url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return send_file(buf, mimetype="image/png")
    return render_template("generate_qr.html")

@app.route("/login/<token>", endpoint="login_by_qr")
def login_by_qr(token):
    with get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT name, role FROM staff WHERE login_token=?", (token,))
        row = c.fetchone()
    if not row:
        return "invalid QR", 403
    session["staff_name"] = row[0]
    session["staff_role"] = row[1]
    flash(_("ログインしました。"))
    return redirect(url_for("home"))

# テンプレ互換用の別名
app.add_url_rule("/login/<token>", endpoint="staff_admin_bp.login_by_qr", view_func=login_by_qr)

# ------------------------------------------------------------
# 利用者一覧/登録/削除（管理者）
# ------------------------------------------------------------
@app.route("/users")
@admin_required
def users_page():
    with get_db() as conn:
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
        with get_db() as conn:
            c = conn.cursor()
            c.execute("INSERT INTO users(name,age,gender,room_number,notes) VALUES(?,?,?,?,?)",
                      (name, age, gender, room_number, notes))
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

# テンプレ互換用エンドポイント名
app.add_url_rule("/users", endpoint="users_bp.users_page", view_func=users_page)
app.add_url_rule("/add_user", endpoint="users_bp.add_user", view_func=add_user, methods=["GET","POST"])

# ------------------------------------------------------------
# 記録一覧/追加（ログイン必須）
# ------------------------------------------------------------
@app.route("/records")
@login_required
def records():
    with get_db() as conn:
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
    # 利用者リスト
    with get_db() as conn:
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
        memo = request.form.get("memo") or ""
        staff_name = session.get("staff_name")

        with get_db() as conn:
            c = conn.cursor()
            c.execute("""
              INSERT INTO records(user_id,meal,medication,toilet,condition,memo,staff_name)
              VALUES(?,?,?,?,?,?,?)
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

# テンプレ互換用エンドポイント名（records_bp.*）
app.add_url_rule("/records", endpoint="records_bp.records", view_func=records)
app.add_url_rule("/add_record", endpoint="records_bp.add_record", view_func=add_record, methods=["GET","POST"])

# ------------------------------------------------------------
# 引継ぎ（GET=一覧、POST=追加）  ※テンプレ互換名も付与
# ------------------------------------------------------------
def _ensure_handover_table():
    with get_db() as conn:
        c = conn.cursor()
        c.execute("""
          CREATE TABLE IF NOT EXISTS handover(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            h_date TEXT,
            shift TEXT,
            note TEXT,
            staff TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
          )
        """)
        conn.commit()

@app.route("/handover", methods=["GET", "POST"])
@login_required
def handover():
    _ensure_handover_table()
    with get_db() as conn:
        c = conn.cursor()
        if request.method == "POST":
            h_date = request.form.get("h_date") or date.today().isoformat()
            shift = request.form.get("shift", "")
            note = request.form.get("note", "")
            staff = request.form.get("staff", "")
            c.execute("INSERT INTO handover(h_date,shift,note,staff) VALUES(?,?,?,?)",
                      (h_date, shift, note, staff))
            conn.commit()
            flash(_("引継ぎを追加しました。"))
            return redirect(url_for("handover"))

        q_date = request.args.get("date") or date.today().isoformat()
        c.execute("""SELECT id, h_date, shift, note, staff
                      FROM handover
                     WHERE h_date=?
                  ORDER BY id DESC""", (q_date,))
        rows = c.fetchall()
    return render_template("handover.html", rows=rows, today=q_date)

# blueprint風の名前でも動くようにエンドポイント別名を登録
app.add_url_rule("/handover", endpoint="handover_bp.handover", view_func=handover, methods=["GET","POST"])

# 旧テンプレが使っている可能性がある /handover/add も提供
@app.route("/handover/add", methods=["POST"])
@login_required
def handover_add():
    return handover()

# ------------------------------------------------------------
# メイン
# ------------------------------------------------------------
if __name__ == "__main__":
    # 自動初期化（既存DBなら無害）
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
