from flask import Flask, render_template, request, redirect, send_file, session, url_for, flash
from functools import wraps
import sqlite3
import qrcode
import io
import secrets
import os
from datetime import date

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

DB_PATH = "care.db"

# -------------------------
# DB 接続ユーティリティ
# -------------------------
def get_connection():
    # row_factoryで列名アクセスしたい時は sqlite3.Row にすることもできる
    return sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)

# -------------------------
# 初期化 & マイグレーション
# -------------------------
def init_db():
    with get_connection() as conn:
        c = conn.cursor()
        # 利用者
        c.execute("""
        CREATE TABLE IF NOT EXISTS users (
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
        CREATE TABLE IF NOT EXISTS records (
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
        CREATE TABLE IF NOT EXISTS staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            password TEXT,
            role TEXT,          -- '管理者' か 'スタッフ'
            login_token TEXT
        )
        """)

        # 引継ぎ
        c.execute("""
        CREATE TABLE IF NOT EXISTS handover_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            on_date TEXT,       -- 'YYYY-MM-DD'
            shift TEXT,         -- '日勤/遅番/夜勤' など
            resident TEXT,      -- 入居者名 or 対象
            priority TEXT,      -- '高/中/低'
            content TEXT,       -- 内容
            staff_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # ---- 既存DBマイグレーション（不足カラム追加） ----
        # records.staff_name が無いDBのためのケア
        c.execute("PRAGMA table_info(records)")
        cols = [r[1] for r in c.fetchall()]
        if "staff_name" not in cols:
            c.execute("ALTER TABLE records ADD COLUMN staff_name TEXT")

        # staff.role が無い・NULLの人に既定値
        c.execute("PRAGMA table_info(staff)")
        s_cols = [r[1] for r in c.fetchall()]
        if "role" in s_cols:
            c.execute("UPDATE staff SET role=COALESCE(role,'スタッフ') WHERE role IS NULL")

        conn.commit()

if not os.path.exists(DB_PATH):
    init_db()
else:
    # 既存DBでも起動時にマイグレーションかける
    init_db()

# -------------------------
# デコレータ
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
        if "staff_name" not in session:
            flash("ログインしてください。")
            return redirect(url_for("staff_login"))
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT role FROM staff WHERE name=?", (session["staff_name"],))
            row = c.fetchone()
        if not row or row[0] != "管理者":
            return "❌ 管理者権限が必要です。", 403
        return f(*args, **kwargs)
    return wrapper

# -------------------------
# ホーム（あなたが選んだ2枚目のメニューUI）
# -------------------------
@app.route("/")
def home():
    staff_name = session.get("staff_name")
    staff_role = session.get("staff_role")
    return render_template("home.html", staff_name=staff_name, staff_role=staff_role)

# -------------------------
# 開発用：自動ログイン（URL直叩きで即ログイン）
# -------------------------
@app.route("/dev_login")
def dev_login():
    session["staff_name"] = "田中"        # 必要なら自由に変えてOK
    session["staff_role"] = "管理者"      # 管理者でログイン
    flash("開発用に自動ログインしました（管理者）")
    return redirect(url_for("home"))

# -------------------------
# スタッフ登録 & ログイン & ログアウト
# -------------------------
@app.route("/staff_register", methods=["GET", "POST"])
def staff_register():
    if request.method == "POST":
        name = request.form.get("name")
        password = request.form.get("password")
        role = request.form.get("role") or "スタッフ"
        try:
            with get_connection() as conn:
                c = conn.cursor()
                c.execute("INSERT INTO staff (name, password, role) VALUES (?, ?, ?)",
                          (name, password, role))
                conn.commit()
            flash("スタッフ登録が完了しました。ログインしてください。")
            return redirect(url_for("staff_login"))
        except sqlite3.IntegrityError:
            flash("同じ名前のスタッフが既に存在します。")
    return render_template("staff_register.html")

@app.route("/staff_login", methods=["GET", "POST"])
def staff_login():
    if request.method == "POST":
        name = request.form.get("name")
        password = request.form.get("password")
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT name, role FROM staff WHERE name=? AND password=?",
                      (name, password))
            staff = c.fetchone()
        if staff:
            session["staff_name"] = staff[0]
            session["staff_role"] = staff[1]
            flash(f"{staff[0]} さんでログインしました。")
            return redirect(url_for("home"))
        else:
            flash("ログイン失敗：名前またはパスワードを確認してください。")
    return render_template("staff_login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("ログアウトしました。")
    return redirect(url_for("home"))

# -------------------------
# 利用者：一覧・追加・削除
# -------------------------
@app.route("/users")
@login_required
def users_page():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM users ORDER BY id")
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
            c.execute("""INSERT INTO users (name, age, gender, room_number, notes)
                         VALUES (?, ?, ?, ?, ?)""",
                      (name, age, gender, room_number, notes))
            conn.commit()
        flash("利用者を登録しました。")
        return redirect(url_for("users_page"))
    return render_template("add_user.html")

@app.route("/delete_user/<int:user_id>", methods=["POST"])
@admin_required
def delete_user(user_id):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
    flash("利用者を削除しました。")
    return redirect(url_for("users_page"))

# -------------------------
# 記録：一覧・追加
# -------------------------
@app.route("/records")
@login_required
def records():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
          SELECT r.id, u.name, r.meal, r.medication, r.toilet, r.condition, r.memo, r.staff_name, r.created_at
            FROM records r
            JOIN users u ON r.user_id = u.id
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
              INSERT INTO records (user_id, meal, medication, toilet, condition, memo, staff_name)
              VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (user_id, meal, medication, toilet, condition, memo, staff_name))
            conn.commit()
        flash("記録を保存しました。")
        return redirect(url_for("records"))

    return render_template("add_record.html", users=users)

# -------------------------
# 引継ぎボード（一覧＋追加＋削除）
# -------------------------
@app.route("/handover", methods=["GET", "POST"])
@login_required
def handover():
    # 追加
    if request.method == "POST":
        on_date = request.form.get("on_date") or date.today().isoformat()
        shift = request.form.get("shift") or ""
        resident = request.form.get("resident") or ""
        priority = request.form.get("priority") or "中"
        content = request.form.get("content") or ""
        staff_name = session.get("staff_name")
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("""
             INSERT INTO handover_items (on_date, shift, resident, priority, content, staff_name)
             VALUES (?, ?, ?, ?, ?, ?)
            """, (on_date, shift, resident, priority, content, staff_name))
            conn.commit()
        flash("引継ぎを追加しました。")
        return redirect(url_for("handover"))

    # 一覧
    on_date = request.args.get("date") or date.today().isoformat()
    shift = request.args.get("shift") or ""
    params = [on_date]
    q = "SELECT id, on_date, shift, resident, priority, content, staff_name, created_at FROM handover_items WHERE on_date=?"
    if shift:
        q += " AND shift=?"
        params.append(shift)
    q += " ORDER BY id DESC"

    with get_connection() as conn:
        c = conn.cursor()
        c.execute(q, tuple(params))
        items = c.fetchall()

    return render_template("handover.html", items=items, on_date=on_date, shift=shift)

@app.route("/handover/<int:item_id>/delete", methods=["POST"])
@login_required
def handover_delete(item_id):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM handover_items WHERE id=?", (item_id,))
        conn.commit()
    flash("引継ぎを削除しました。")
    return redirect(url_for("handover"))

# -------------------------
# スタッフ管理（一覧・QR）
# -------------------------
@app.route("/staff_list")
@admin_required
def staff_list():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT * FROM staff ORDER BY id")
        staff_list = c.fetchall()
    return render_template("staff_list.html", staff_list=staff_list)

@app.route("/qr/<name>")
@admin_required
def qr_reissue(name):
    token = secrets.token_hex(8)
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE staff SET login_token=? WHERE name=?", (token, name))
        if c.rowcount == 0:
            # 未登録ならスタッフとして作る（安全性より利便性重視の開発用）
            c.execute("INSERT INTO staff (name, password, role, login_token) VALUES (?, ?, ?, ?)",
                      (name, "temp", "スタッフ", token))
        conn.commit()

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
        role = request.form.get("role") or "スタッフ"
        token = secrets.token_hex(8)
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO staff (name, role, login_token) VALUES (?, ?, ?)",
                      (name, role, token))
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
def login(token):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT name, role FROM staff WHERE login_token=?", (token,))
        staff = c.fetchone()
    if staff:
        session["staff_name"] = staff[0]
        session["staff_role"] = staff[1]
        flash(f"{staff[0]} さんでログインしました。")
        return redirect(url_for("home"))
    return "❌ 無効なQRコードです。再発行してください。", 403

# -------------------------
# 実行
# -------------------------
if __name__ == "__main__":
    # ローカル起動は http://127.0.0.1:5000
    app.run(host="0.0.0.0", port=5000, debug=True)
