from flask import Flask, render_template, request, redirect, send_file, session, url_for, flash, Response
from functools import wraps
import sqlite3
import qrcode
import io
import secrets
import os
from datetime import date
import csv

app = Flask(__name__)

from extras.staff_admin import staff_admin_bp
app.register_blueprint(staff_admin_bp)

app.secret_key = secrets.token_hex(16)
DB_PATH = "care.db"

# -------------------------
# DB 接続 & 初期化/マイグレーション
# -------------------------
def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    return conn

def _ensure_columns(conn, table, columns):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    exist = {r[1] for r in cur.fetchall()}
    for col, typ in columns:
        if col not in exist:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")

def init_db():
    with get_connection() as conn:
        c = conn.cursor()
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
        c.execute("""
            CREATE TABLE IF NOT EXISTS staff(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT UNIQUE,
              password TEXT,
              role TEXT,
              login_token TEXT
            )
        """)
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
        _ensure_columns(conn, "records", [
            ("staff_name", "TEXT"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        ])
        _ensure_columns(conn, "staff", [
            ("password", "TEXT"),
            ("role", "TEXT"),
            ("login_token", "TEXT")
        ])
        _ensure_columns(conn, "handover", [
            ("on_date", "TEXT"),
            ("shift", "TEXT"),
            ("resident_id", "INTEGER"),
            ("priority", "INTEGER"),
            ("title", "TEXT"),
            ("body", "TEXT"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        ])
        conn.commit()
init_db()

# -------------------------
# 認証デコレータ
# -------------------------
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "staff_name" not in session:
            flash("ログインが必要です。")
            return redirect(url_for("staff_login"))
        return f(*args, **kwargs)
    return wrapper

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("staff_role") != "admin":
            return "❌ 管理者権限が必要です。", 403
        return f(*args, **kwargs)
    return wrapper

# -------------------------
# ホーム
# -------------------------
@app.route("/")
def home():
    return render_template("home.html",
                           staff_name=session.get("staff_name"),
                           staff_role=session.get("staff_role"))

# -------------------------
# スタッフ登録・ログイン・ログアウト
# -------------------------
@app.route("/staff_register", methods=["GET", "POST"])
def staff_register():
    if request.method == "POST":
        name = request.form.get("name")
        password = request.form.get("password")
        role = "caregiver"
        with get_connection() as conn:
            c = conn.cursor()
            try:
                c.execute("INSERT INTO staff (name, password, role) VALUES (?, ?, ?)",
                          (name, password, role))
                conn.commit()
                flash("登録完了。ログインしてください。")
                return redirect(url_for("staff_login"))
            except sqlite3.IntegrityError:
                flash("同名のスタッフがすでに存在します。")
    return render_template("staff_register.html")

@app.route("/staff_login", methods=["GET", "POST"])
def staff_login():
    if request.method == "POST":
        name = request.form.get("name")
        password = request.form.get("password")
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT name, role FROM staff WHERE name=? AND password=?", (name, password))
            s = c.fetchone()
        if s:
            session["staff_name"], session["staff_role"] = s[0], s[1]
            flash(f"{s[0]} さんでログインしました。")
            return redirect(url_for("home"))
        flash("名前またはパスワードが違います。")
    return render_template("staff_login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("ログアウトしました。")
    return redirect(url_for("home"))

# -------------------------
# 利用者管理
# -------------------------
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
            c.execute("""INSERT INTO users(name, age, gender, room_number, notes)
                         VALUES(?,?,?,?,?)""",
                      (request.form.get("name"),
                       request.form.get("age"),
                       request.form.get("gender"),
                       request.form.get("room_number"),
                       request.form.get("notes")))
            conn.commit()
        flash("利用者を登録しました。")
        return redirect(url_for("users_page"))
    return render_template("add_user.html")

@app.route("/delete_user/<int:user_id>", methods=["POST", "GET"])
@admin_required
def delete_user(user_id):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
    flash("利用者を削除しました。")
    return redirect(url_for("users_page"))

# -------------------------
# 記録（プルダウン式）
# -------------------------
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
        def pick(val, other):
            other = (other or "").strip()
            return other if (val == "その他" and other) else val

        with get_connection() as conn:
            c = conn.cursor()
            c.execute("""INSERT INTO records(user_id, meal, medication, toilet, condition, memo, staff_name)
                         VALUES(?,?,?,?,?,?,?)""",
                      (request.form.get("user_id"),
                       pick(request.form.get("meal"), request.form.get("meal_other")),
                       pick(request.form.get("medication"), request.form.get("medication_other")),
                       pick(request.form.get("toilet"), request.form.get("toilet_other")),
                       pick(request.form.get("condition"), request.form.get("condition_other")),
                       request.form.get("memo"),
                       session.get("staff_name")))
            conn.commit()
        flash("記録を保存しました。")
        return redirect(url_for("records"))

    return render_template("add_record.html",
                           users=users,
                           MEAL_CHOICES=MEAL_CHOICES,
                           MEDICATION_CHOICES=MEDICATION_CHOICES,
                           TOILET_CHOICES=TOILET_CHOICES,
                           CONDITION_CHOICES=CONDITION_CHOICES)

# -------------------------
# 引継ぎボード
# -------------------------
@app.route("/handover")
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
        c.execute("""INSERT INTO handover(on_date, shift, resident_id, priority, title, body)
                     VALUES(?,?,?,?,?,?)""",
                  (request.form.get("on_date") or date.today().isoformat(),
                   request.form.get("shift") or "day",
                   request.form.get("resident_id"),
                   request.form.get("priority") or 2,
                   request.form.get("title"),
                   request.form.get("body")))
        conn.commit()
    flash("引継ぎを追加しました。")
    return redirect(url_for("handover",
                            date=request.form.get("on_date") or date.today().isoformat(),
                            shift=request.form.get("shift") or "day"))

@app.route("/handover/export")
@admin_required
def handover_export():
    on_date = request.args.get("date") or date.today().isoformat()
    shift = request.args.get("shift") or "day"
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT h.on_date, h.shift, IFNULL(u.name, ''), h.priority, h.title, h.body, h.created_at
            FROM handover h LEFT JOIN users u ON h.resident_id = u.id
            WHERE h.on_date=? AND h.shift=?
            ORDER BY h.priority ASC, h.id DESC
        """, (on_date, shift))
        rows = c.fetchall()

    def gen():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["日付", "シフト", "利用者", "優先度", "件名", "本文", "作成日時"])
        yield output.getvalue()
        output.seek(0); output.truncate(0)
        for r in rows:
            writer.writerow(r)
            yield output.getvalue()
            output.seek(0); output.truncate(0)

    filename = f"handover_{on_date}_{shift}.csv"
    return Response(gen(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})

# -------------------------
# 管理者ページ＆スタッフ管理
# -------------------------
@app.route("/admin")
@admin_required
def admin_page():
    return render_template("admin.html", staff_name=session.get("staff_name"))

@app.route("/staff_list")
@admin_required
def staff_list():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, password, role, login_token FROM staff ORDER BY id")
        staff = c.fetchall()
    return render_template("staff_list.html", staff_list=staff)

@app.route("/qr/<name>")
@admin_required
def qr_reissue(name):
    token = secrets.token_hex(8)
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE staff SET login_token=? WHERE name=?", (token, name))
        conn.commit()
    host = request.host.split(":")[0]
    login_url = f"http://{host}:5000/login/{token}"
    img = qrcode.make(login_url)
    buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
    return send_file(buf, mimetype="image/png")

@app.route("/delete_staff/<int:sid>")
@admin_required
def delete_staff(sid):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM staff WHERE id=?", (sid,))
        conn.commit()
    flash("スタッフを削除しました。")
    return redirect(url_for("staff_list"))

# -------------------------
# QRログイン (login / login_by_qr)
# -------------------------
@app.route("/login/<token>")
def login(token):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT name, role FROM staff WHERE login_token=?", (token,))
        s = c.fetchone()
    if not s:
        return "無効なQRコードです。", 403
    session["staff_name"], session["staff_role"] = s[0], s[1]
    flash(f"{s[0]} さんでログインしました。")
    return redirect(url_for("home"))

@app.route("/login_by_qr/<token>")
def login_by_qr(token):
    return login(token)

# -------------------------
# 起動
# -------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
