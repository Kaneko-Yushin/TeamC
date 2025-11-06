# extras/staff_admin.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, session, current_app
import sqlite3, secrets, qrcode, io, os
from functools import wraps

staff_admin_bp = Blueprint("staff_admin", __name__, url_prefix="/admin/staff")

# -------------------------
# adminチェック（app.pyと独立させるためここで定義）
# -------------------------
def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        role = session.get("staff_role")
        if role != "admin":
            return "❌ 管理者権限が必要です。", 403
        return f(*args, **kwargs)
    return wrapper

# -------------------------
# DB接続（app.pyに依存しない）
# -------------------------
def _db_path():
    # app.config['DB_PATH'] があればそれを使う。なければプロジェクト直下の care.db
    return current_app.config.get("DB_PATH", os.path.join(current_app.root_path, "care.db"))

def get_connection():
    return sqlite3.connect(_db_path(), timeout=10, check_same_thread=False)

# -------------------------
# 一覧
# -------------------------
@staff_admin_bp.route("/", methods=["GET"])
@admin_required
def list():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, password, role, login_token FROM staff ORDER BY id")
        staff = c.fetchall()
    return render_template("staff_list.html", staff_list=staff)

# -------------------------
# 新規追加（GETフォーム & POST登録）
# -------------------------
@staff_admin_bp.route("/add", methods=["GET", "POST"])
@admin_required
def add():
    if request.method == "POST":
        name = request.form.get("name")
        password = request.form.get("password") or ""
        role = request.form.get("role") or "caregiver"
        with get_connection() as conn:
            c = conn.cursor()
            try:
                c.execute("INSERT INTO staff (name, password, role) VALUES (?, ?, ?)", (name, password, role))
                conn.commit()
                flash("スタッフを追加しました。")
                return redirect(url_for("staff_admin.list"))
            except sqlite3.IntegrityError:
                flash("同名のスタッフが既に存在します。")
    # 簡易フォーム（テンプレ無しでもOK）
    return render_template("simple_staff_add.html")

# -------------------------
# 編集（名前・役割・パスワード）
# -------------------------
@staff_admin_bp.route("/<int:sid>/edit", methods=["GET", "POST"])
@admin_required
def edit(sid):
    with get_connection() as conn:
        c = conn.cursor()
        if request.method == "POST":
            name = request.form.get("name")
            password = request.form.get("password")
            role = request.form.get("role")
            # パスワード空なら変更しない
            if password:
                c.execute("UPDATE staff SET name=?, password=?, role=? WHERE id=?", (name, password, role, sid))
            else:
                c.execute("UPDATE staff SET name=?, role=? WHERE id=?", (name, role, sid))
            conn.commit()
            flash("更新しました。")
            return redirect(url_for("staff_admin.list"))
        c.execute("SELECT id, name, password, role, login_token FROM staff WHERE id=?", (sid,))
        row = c.fetchone()
    return render_template("simple_staff_edit.html", s=row)

# -------------------------
# 役割変更（一覧のプルダウン用）
# -------------------------
@staff_admin_bp.route("/<int:sid>/role", methods=["POST"])
@admin_required
def change_role(sid):
    role = request.form.get("role") or "caregiver"
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE staff SET role=? WHERE id=?", (role, sid))
        conn.commit()
    flash("役割を変更しました。")
    return redirect(url_for("staff_admin.list"))

# -------------------------
# パスワード再発行（仮パス生成）
# -------------------------
@staff_admin_bp.route("/<int:sid>/reset_password", methods=["POST"])
@admin_required
def reset_password(sid):
    new_pass = secrets.token_hex(4)
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE staff SET password=? WHERE id=?", (new_pass, sid))
        conn.commit()
    flash(f"仮パスワードを発行: {new_pass}")
    return redirect(url_for("staff_admin.list"))

# -------------------------
# QR再発行（トークン生成してPNG返却）
# -------------------------
@staff_admin_bp.route("/<int:sid>/qr", methods=["GET"])
@admin_required
def qr(sid):
    # 新トークン生成して保存
    token = secrets.token_hex(8)
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE staff SET login_token=? WHERE id=?", (token, sid))
        conn.commit()
    # ログインURLをQR化
    host = request.host.split(":")[0]
    login_url = f"http://{host}:5000/login/{token}"

    img = qrcode.make(login_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

# -------------------------
# 削除
# -------------------------
@staff_admin_bp.route("/<int:sid>/delete", methods=["POST"])
@admin_required
def delete(sid):
    # 自分自身（admin）を消すとハマるので注意喚起だけして普通に消す
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM staff WHERE id=?", (sid,))
        conn.commit()
    flash("スタッフを削除しました。")
    return redirect(url_for("staff_admin.list"))
