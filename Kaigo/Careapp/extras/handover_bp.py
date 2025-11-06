from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from functools import wraps
from datetime import date
from extras.db import get_conn
from extras.i18n import _

handover_bp = Blueprint("handover_bp", __name__)

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "staff_name" not in session:
            flash(_("login_needed"))
            return redirect(url_for("auth_bp.staff_login"))
        return f(*args, **kwargs)
    return wrapper

@handover_bp.route("/handover", methods=["GET"])
@login_required
def handover():
    on_date = request.args.get("date") or date.today().isoformat()
    shift = request.args.get("shift") or "day"
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name FROM users ORDER BY id")
        residents = c.fetchall()
        c.execute("""
            SELECT h.id, h.on_date, h.shift, u.name, h.priority, h.title, h.body, h.created_at
            FROM handover h LEFT JOIN users u ON h.resident_id = u.id
            WHERE h.on_date=? AND h.shift=?
            ORDER BY h.priority ASC, h.id DESC
        """,(on_date, shift))
        items = c.fetchall()
    return render_template("handover.html", items=items, residents=residents, on_date=on_date, shift=shift)

@handover_bp.route("/handover/add", methods=["POST"])
@login_required
def handover_add():
    on_date = request.form.get("on_date") or date.today().isoformat()
    shift = request.form.get("shift") or "day"
    resident_id = request.form.get("resident_id") or None
    priority = request.form.get("priority") or 2
    title = request.form.get("title") or ""
    body = request.form.get("body") or ""
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
          INSERT INTO handover(on_date, shift, resident_id, priority, title, body)
          VALUES(?,?,?,?,?,?)
        """,(on_date, shift, resident_id, priority, title, body))
        conn.commit()
    flash(_("handover_added"))
    return redirect(url_for("handover_bp.handover", date=on_date, shift=shift))
