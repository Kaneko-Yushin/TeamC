from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from functools import wraps
from extras.db import get_conn
from extras.i18n import _

users_bp = Blueprint("users_bp", __name__)

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if session.get("staff_role") != "admin":
            return _("admin_needed"), 403
        return f(*args, **kwargs)
    return wrapper

@users_bp.route("/users")
@admin_required
def users_page():
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, age, gender, room_number, notes FROM users ORDER BY id")
        users = c.fetchall()
    return render_template("users.html", users=users)

@users_bp.route("/add_user", methods=["GET","POST"])
@admin_required
def add_user():
    if request.method == "POST":
        name = request.form.get("name")
        age = request.form.get("age")
        gender = request.form.get("gender")
        room = request.form.get("room_number")
        notes = request.form.get("notes")
        with get_conn() as conn:
            c = conn.cursor()
            c.execute("INSERT INTO users(name,age,gender,room_number,notes) VALUES(?,?,?,?,?)",
                      (name,age,gender,room,notes))
            conn.commit()
        flash(_("user_added"))
        return redirect(url_for("users_bp.users_page"))
    return render_template("add_user.html")

@users_bp.route("/delete_user/<int:user_id>")
@admin_required
def delete_user(user_id):
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
    flash(_("user_deleted"))
    return redirect(url_for("users_bp.users_page"))
