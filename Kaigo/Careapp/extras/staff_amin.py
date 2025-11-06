from flask import Blueprint, render_template, redirect, url_for, flash, request, send_file, session
from functools import wraps
from extras.db import get_conn
from extras.i18n import _
import secrets, qrcode, io

staff_admin_bp = Blueprint("staff_admin_bp", __name__)

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("staff_role") != "admin":
            return _("admin_needed"), 403
        return f(*args, **kwargs)
    return wrapper

@staff_admin_bp.route("/admin")
def admin_page():
    if "staff_name" not in session:
        flash(_("login_needed"))
        return redirect(url_for("auth_bp.staff_login"))
    return render_template("admin.html")

@staff_admin_bp.route("/staff_list")
@admin_required
def staff_list():
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, password, role, login_token FROM staff ORDER BY id")
        staff = c.fetchall()
    return render_template("staff_list.html", staff_list=staff)

@staff_admin_bp.route("/qr/<name>")
@admin_required
def qr_reissue(name):
    token = secrets.token_hex(8)
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("UPDATE staff SET login_token=? WHERE name=?", (token, name))
        conn.commit()
    flash("OK")
    return redirect(url_for("staff_admin_bp.staff_list"))

@staff_admin_bp.route("/delete_staff/<int:sid>")
@admin_required
def delete_staff(sid):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM staff WHERE id=?", (sid,))
        conn.commit()
    flash("OK")
    return redirect(url_for("staff_admin_bp.staff_list"))

@staff_admin_bp.route("/generate_qr", methods=["GET","POST"])
@admin_required
def generate_qr():
    if request.method == "POST":
        name = request.form.get("name")
        role = request.form.get("role") or "caregiver"
        token = secrets.token_hex(8)
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO staff(name, role, login_token) VALUES(?,?,?)",
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

@staff_admin_bp.route("/login/<token>")
def login_by_qr(token):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT name, role FROM staff WHERE login_token=?", (token,))
        row = c.fetchone()
    if not row:
        return _("invalid_qr"), 403
    session["staff_name"] = row[0]
    session["staff_role"] = row[1]
    flash(_("hello_login") % row[0])
    return redirect(url_for("home"))
