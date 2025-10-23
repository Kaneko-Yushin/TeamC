from flask import (
    Flask, render_template, request, redirect, send_file,
    session, url_for, flash, Response
)
from functools import wraps
from datetime import date
import sqlite3
import io
    # noqa
import csv
import secrets
import os

# ▼ Socket.IO（引継ぎのリアルタイム更新）
from flask_socketio import SocketIO

# ▼ QRコード（任意）
try:
    import qrcode
    QR_AVAILABLE = True
except Exception:
    QR_AVAILABLE = False

app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET", secrets.token_hex(16))

socketio = SocketIO(app, cors_allowed_origins="*")

DB_PATH = "care.db"

# ===============================================================
# DB ユーティリティ
# ===============================================================
def get_connection():
    # 使う箇所で必要なら row_factory を設定する想定
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

        # 職員
        c.execute("""
        CREATE TABLE IF NOT EXISTS staff(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            email TEXT,
            role TEXT,           -- 'admin' / 'nurse' / 'caregiver'
            password TEXT,
            login_token TEXT
        )
        """)

        # 引継ぎ（日付×シフト）
        c.execute("""
        CREATE TABLE IF NOT EXISTS handover_days (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            on_date TEXT NOT NULL,
            shift TEXT NOT NULL,
            UNIQUE(on_date, shift)
        )
        """)

        # 引継ぎアイテム
        c.execute("""
        CREATE TABLE IF NOT EXISTS handover_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            handover_id INTEGER NOT NULL,
            resident_id INTEGER,
            title TEXT NOT NULL,
            detail TEXT,
            priority TEXT NOT NULL DEFAULT 'medium',
            created_by TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(handover_id) REFERENCES handover_days(id),
            FOREIGN KEY(resident_id) REFERENCES users(id)
        )
        """)
        conn.commit()

# ===============================================================
# 既存DB救済（ALTER 制約に対応）
# ===============================================================
if not os.path.exists(DB_PATH):
    init_db()
else:
    with get_connection() as conn:
        c = conn.cursor()

        # staff テーブル：古いDBの不足カラムを補完
        try: c.execute("ALTER TABLE staff ADD COLUMN email TEXT")
        except: pass
        try: c.execute("ALTER TABLE staff ADD COLUMN password TEXT")
        except: pass
        try: c.execute("ALTER TABLE staff ADD COLUMN login_token TEXT")
        except: pass

        # records テーブル：不足カラムを補完
        c.execute("PRAGMA table_info(records)")
        rec_cols = [row[1] for row in c.fetchall()]

        if "staff_name" not in rec_cols:
            c.execute("ALTER TABLE records ADD COLUMN staff_name TEXT")

        # SQLiteは ALTER で DEFAULT CURRENT_TIMESTAMP を追加できないのでTEXTで追加→既存行を埋める
        if "created_at" not in rec_cols:
            c.execute("ALTER TABLE records ADD COLUMN created_at TEXT")
            c.execute("UPDATE records SET created_at = datetime('now','localtime') WHERE created_at IS NULL")

        conn.commit()

        # 以降のINSERTで created_at が空なら自動補完するトリガー（無ければ作成）
        try:
            c.execute("""
                CREATE TRIGGER records_set_created_at
                AFTER INSERT ON records
                FOR EACH ROW
                WHEN NEW.created_at IS NULL
                BEGIN
                    UPDATE records
                    SET created_at = datetime('now','localtime')
                    WHERE id = NEW.id;
                END;
            """)
            conn.commit()
        except sqlite3.OperationalError:
            # 既に存在する等は無視
            pass

# ===============================================================
# 役割ヘルパ
# ===============================================================
def role_label(role):
    return {"admin": "管理者", "nurse": "看護師", "caregiver": "介護士"}.get(role or "", "スタッフ")

def is_logged_in():
    return "staff_name" in session

def current_role_internal():
    return session.get("staff_role")

# ===============================================================
# デコレータ
# ===============================================================
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_logged_in():
            flash("ログインが必要です。")
            return redirect(url_for("staff_login"))
        return f(*args, **kwargs)
    return wrapper

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not is_logged_in():
            flash("ログインしてください。")
            return redirect(url_for("staff_login"))
        if current_role_internal() != "admin":
            return "❌ 管理者権限が必要です。", 403
        return f(*args, **kwargs)
    return wrapper

# ===============================================================
# ホーム
# ===============================================================
@app.route("/")
def home():
    staff_name = session.get("staff_name")
    staff_role = role_label(session.get("staff_role"))
    return render_template("home.html", staff_name=staff_name, staff_role=staff_role)

# ===============================================================
# スタッフ登録 / ログイン / ログアウト
# ===============================================================
@app.route("/staff_register", methods=["GET", "POST"])
def staff_register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "").strip()
        role = "caregiver"  # 新規は介護士に寄せる
        if not name or not password:
            flash("名前とパスワードは必須です。")
            return render_template("staff_register.html")
        try:
            with get_connection() as conn:
                c = conn.cursor()
                c.execute("INSERT INTO staff(name,password,role) VALUES(?,?,?)", (name, password, role))
                conn.commit()
            flash("スタッフ登録が完了しました。ログインしてください。")
            return redirect(url_for("staff_login"))
        except sqlite3.IntegrityError:
            flash("同じ名前のスタッフが既に存在します。")
    return render_template("staff_register.html")

@app.route("/staff_login", methods=["GET", "POST"])
def staff_login():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "").strip()
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT name, role FROM staff WHERE name=? AND password=?", (name, password))
            row = c.fetchone()
        if row:
            session["staff_name"] = row[0]
            session["staff_role"] = row[1]  # admin / nurse / caregiver
            flash(f"{row[0]} さんでログインしました。")
            return redirect(url_for("home"))
        flash("ログイン失敗：名前またはパスワードを確認してください。")
    return render_template("staff_login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("ログアウトしました。")
    return redirect(url_for("home"))

# ===============================================================
# 管理：ダッシュボード / スタッフ一覧・QR / トークンログイン
# ===============================================================
@app.route("/admin")
@login_required
def admin_page():
    return render_template("admin.html", staff_name=session.get("staff_name"))

@app.route("/staff_list")
@admin_required
def staff_list():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id,name,email,role,login_token FROM staff ORDER BY id DESC")
        staff = c.fetchall()
    return render_template("staff_list.html", staff_list=staff, role_label=role_label)

@app.route("/delete_staff/<int:staff_id>")
@admin_required
def delete_staff(staff_id):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM staff WHERE id=?", (staff_id,))
        conn.commit()
    flash("スタッフを削除しました。")
    return redirect(url_for("staff_list"))

@app.route("/qr/<name>")
@admin_required
def qr_reissue(name):
    if not QR_AVAILABLE:
        return "QRコードライブラリが利用できません。", 500
    token = secrets.token_hex(8)
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE staff SET login_token=? WHERE name=?", (token, name))
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
        name = request.form.get("name", "").strip()
        role = request.form.get("role", "caregiver").strip()
        if not name:
            flash("名前は必須です。")
            return render_template("generate_qr.html")
        token = secrets.token_hex(8)
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO staff(name, role, login_token)
                VALUES(?,?,?)
                ON CONFLICT(name) DO UPDATE SET role=excluded.role, login_token=excluded.login_token
            """, (name, role, token))
            conn.commit()
        if not QR_AVAILABLE:
            flash(f"QR生成不可。トークン: {token}")
            return redirect(url_for("staff_list"))
        host = request.host.split(":")[0]
        login_url = f"http://{host}:5000/login/{token}"
        img = qrcode.make(login_url)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return send_file(buf, mimetype="image/png")
    return render_template("generate_qr.html")

@app.route("/login/<token>")
def login_with_token(token):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT name, role FROM staff WHERE login_token=?", (token,))
        row = c.fetchone()
    if not row:
        return "❌ 無効なQRコードです。再発行してください。", 403
    session["staff_name"] = row[0]
    session["staff_role"] = row[1]
    flash(f"{row[0]} さんでログインしました。")
    return redirect(url_for("home"))

# ===============================================================
# アカウント管理（accounts：一覧/新規/編集/削除）※管理者のみ
# ===============================================================
@app.route("/accounts")
@admin_required
def accounts():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, COALESCE(email,''), COALESCE(role,'') FROM staff ORDER BY id DESC")
        staff = c.fetchall()
    return render_template("accounts.html", staff=staff, role_label=role_label)

@app.route("/accounts/add", methods=["GET", "POST"])
@admin_required
def accounts_add():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        role  = request.form.get("role", "caregiver").strip()
        password = request.form.get("password", "").strip() or secrets.token_hex(4)
        with get_connection() as conn:
            conn.row_factory = sqlite3.Row
            c = conn.cursor()
            dup = c.execute("SELECT id FROM staff WHERE email=? AND email<>''", (email,)).fetchone()
            if dup:
                return render_template("accounts_add.html", error="そのメールは既に登録されています。", _name=name, _email=email, _role=role)
            try:
                c.execute("INSERT INTO staff(name, email, role, password) VALUES(?,?,?,?)",
                          (name, email, role, password))
                conn.commit()
            except sqlite3.IntegrityError:
                return render_template("accounts_add.html", error="同名の職員が既にいます。別名で登録してください。", _name=name, _email=email, _role=role)
        flash("アカウントを作成しました。")
        return redirect(url_for("accounts"))
    return render_template("accounts_add.html")

@app.route("/accounts/<int:staff_id>/edit", methods=["GET", "POST"])
@admin_required
def accounts_edit(staff_id):
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip()
            role  = request.form.get("role", "caregiver").strip()
            password = request.form.get("password", "").strip()
            dup = c.execute("SELECT id FROM staff WHERE email=? AND id<>? AND email<>''", (email, staff_id)).fetchone()
            if dup:
                staff = c.execute("SELECT * FROM staff WHERE id=?", (staff_id,)).fetchone()
                return render_template("accounts_edit.html", staff=staff, error="そのメールは他のアカウントで使用されています。")
            if password:
                c.execute("UPDATE staff SET name=?, email=?, role=?, password=? WHERE id=?",
                          (name, email, role, password, staff_id))
            else:
                c.execute("UPDATE staff SET name=?, email=?, role=? WHERE id=?",
                          (name, email, role, staff_id))
            conn.commit()
            flash("アカウントを更新しました。")
            return redirect(url_for("accounts"))
        staff = c.execute("SELECT * FROM staff WHERE id=?", (staff_id,)).fetchone()
        if not staff:
            return redirect(url_for("accounts"))
        return render_template("accounts_edit.html", staff=staff)

@app.route("/accounts/<int:staff_id>/delete", methods=["POST"])
@admin_required
def accounts_delete(staff_id):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM staff WHERE id=?", (staff_id,))
        conn.commit()
    flash("アカウントを削除しました。")
    return redirect(url_for("accounts"))

# ===============================================================
# 利用者（一覧/追加/編集/削除）※管理者のみ
# ===============================================================
@app.route("/users")
@admin_required
def users_page():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, COALESCE(age,''), COALESCE(gender,''), COALESCE(room_number,''), COALESCE(notes,'') FROM users ORDER BY id DESC")
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
            c.execute("""
                INSERT INTO users(name, age, gender, room_number, notes)
                VALUES(?,?,?,?,?)
            """, (name, age, gender, room_number, notes))
            conn.commit()
        flash("利用者を登録しました。")
        return redirect(url_for("users_page"))
    return render_template("add_user.html")

@app.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_user(user_id):
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        if request.method == "POST":
            name = request.form.get("name")
            age = request.form.get("age")
            gender = request.form.get("gender")
            room_number = request.form.get("room_number")
            notes = request.form.get("notes")
            c.execute("""
                UPDATE users SET name=?, age=?, gender=?, room_number=?, notes=? WHERE id=?
            """, (name, age, gender, room_number, notes, user_id))
            conn.commit()
            flash("利用者情報を更新しました。")
            return redirect(url_for("users_page"))
        user = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return render_template("edit_user.html", user=user)

@app.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id):
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
    flash("利用者を削除しました。")
    return redirect(url_for("users_page"))

# ===============================================================
# 記録（一覧/追加）※ログイン必須
# ===============================================================
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
        c.execute("SELECT id, name FROM users ORDER BY id DESC")
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
                INSERT INTO records(user_id, meal, medication, toilet, condition, memo, staff_name, created_at)
                VALUES(?,?,?,?,?,?,?, datetime('now','localtime'))
            """, (user_id, meal, medication, toilet, condition, memo, staff_name))
            conn.commit()
        flash("記録を保存しました。")
        return redirect(url_for("records"))
    selected = request.args.get("user_id")
    return render_template("add_record.html", users=users, selected_user_id=selected)

# ===============================================================
# 引継ぎボード（リアルタイム + CSVエクスポート）※ログイン必須
# ===============================================================
def _get_or_create_handover(on_date, shift):
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        row = c.execute(
            "SELECT id FROM handover_days WHERE on_date=? AND shift=?",
            (on_date, shift)
        ).fetchone()
        if row:
            return row["id"]
        c.execute("INSERT INTO handover_days(on_date, shift) VALUES(?,?)", (on_date, shift))
        conn.commit()
        return c.lastrowid

def _get_item_with_context(item_id):
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        return c.execute("""
            SELECT hi.*, hd.on_date, hd.shift
            FROM handover_items hi
            JOIN handover_days hd ON hd.id = hi.handover_id
            WHERE hi.id=?
        """, (item_id,)).fetchone()

@app.route("/handover")
@login_required
def handover():
    on_date = request.args.get("date") or date.today().isoformat()
    shift = request.args.get("shift") or "日勤"
    hid = _get_or_create_handover(on_date, shift)
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        items = c.execute("""
            SELECT hi.id, u.name AS resident_name, hi.title, hi.detail, hi.priority, hi.created_by, hi.created_at
            FROM handover_items hi
            LEFT JOIN users u ON u.id = hi.resident_id
            WHERE hi.handover_id=?
            ORDER BY CASE hi.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, hi.id DESC
        """, (hid,)).fetchall()
        residents = c.execute("SELECT id, name FROM users ORDER BY name").fetchall()
    return render_template("handover.html", items=items, residents=residents, on_date=on_date, shift=shift)

@app.route("/handover/add", methods=["POST"])
@login_required
def handover_add():
    on_date = request.form.get("on_date") or date.today().isoformat()
    shift = request.form.get("shift") or "日勤"
    title = request.form.get("title") or ""
    detail = request.form.get("detail") or ""
    priority = request.form.get("priority") or "medium"
    resident_id = request.form.get("resident_id") or None
    created_by = session.get("staff_name") or "スタッフ"
    hid = _get_or_create_handover(on_date, shift)
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO handover_items(handover_id, resident_id, title, detail, priority, created_by)
            VALUES(?,?,?,?,?,?)
        """, (hid, resident_id, title, detail, priority, created_by))
        conn.commit()
    socketio.emit('update_handover', {'date': on_date, 'shift': shift})
    return redirect(url_for("handover", date=on_date, shift=shift))

@app.route("/handover/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def handover_edit(item_id):
    row = _get_item_with_context(item_id)
    if not row:
        return redirect(url_for("handover"))
    if request.method == "POST":
        title = request.form.get("title") or ""
        detail = request.form.get("detail") or ""
        priority = request.form.get("priority") or "medium"
        resident_id = request.form.get("resident_id") or None
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("""
                UPDATE handover_items
                   SET title=?, detail=?, priority=?, resident_id=?
                 WHERE id=?
            """, (title, detail, priority, resident_id, item_id))
            conn.commit()
        socketio.emit('update_handover', {'date': row["on_date"], 'shift': row["shift"]})
        return redirect(url_for("handover", date=row["on_date"], shift=row["shift"]))
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        residents = c.execute("SELECT id, name FROM users ORDER BY name").fetchall()
    return render_template("handover_edit.html", item=row, residents=residents)

@app.route("/handover/<int:item_id>/delete", methods=["POST"])
@login_required
def handover_delete(item_id):
    row = _get_item_with_context(item_id)
    if row:
        with get_connection() as conn:
            c = conn.cursor()
            c.execute("DELETE FROM handover_items WHERE id=?", (item_id,))
            conn.commit()
        socketio.emit('update_handover', {'date': row["on_date"], 'shift': row["shift"]})
    return redirect(url_for("handover"))

@app.route("/handover/export")
@login_required
def handover_export():
    on_date = request.args.get("date") or date.today().isoformat()
    shift = request.args.get("shift") or "日勤"
    hid = _get_or_create_handover(on_date, shift)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["日付", on_date, "シフト", shift])
    writer.writerow(["No", "利用者", "タイトル", "詳細", "優先度", "作成者", "作成日時"])
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT hi.id, COALESCE(u.name,''), hi.title, hi.detail, hi.priority, COALESCE(hi.created_by,''), hi.created_at
            FROM handover_items hi
            LEFT JOIN users u ON u.id=hi.resident_id
            WHERE hi.handover_id=?
            ORDER BY hi.id
        """, (hid,))
        for row in c.fetchall():
            writer.writerow(row)
    csv_data = output.getvalue().encode("utf-8-sig")
    filename = f"handover_{on_date}_{shift}.csv"
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# ===============================================================
# 起動
# ===============================================================
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
