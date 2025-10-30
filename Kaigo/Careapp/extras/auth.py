from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from extras.db import get_conn
from extras.i18n import _

auth_bp = Blueprint("auth_bp", __name__)

@auth_bp.route("/staff_register", methods=["GET","POST"])
def staff_register():
    if request.method == "POST":
        name = request.form.get("name")
        password = request.form.get("password")
        role = "caregiver"
        with get_conn() as conn:
            c = conn.cursor()
            try:
                c.execute("INSERT INTO staff (name,password,role) VALUES (?,?,?)",(name,password,role))
                conn.commit()
                flash(_("reg_done"))
                return redirect(url_for("auth_bp.staff_login"))
            except Exception:
                flash(_("dup_staff"))
    return render_template("staff_register.html")

@auth_bp.route("/staff_login", methods=["GET","POST"])
def staff_login():
    if request.method == "POST":
        name = request.form.get("name")
        password = request.form.get("password")
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("SELECT name, role FROM staff WHERE name=? AND password=?", (name, password))
            row = c.fetchone()
        if row:
            session["staff_name"] = row[0]
            session["staff_role"] = row[1]
            flash(_("hello_login") % row[0])
            return redirect(url_for("home"))
        flash(_("login_failed"))
    return render_template("staff_login.html")

@auth_bp.route("/logout")
def logout():
    session.clear()
    flash(_("logged_out"))
    return redirect(url_for("home"))
