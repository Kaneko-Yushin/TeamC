from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from functools import wraps
from extras.db import get_conn
from extras.i18n import _, T, get_lang

records_bp = Blueprint("records_bp", __name__)

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "staff_name" not in session:
            flash(_("login_needed"))
            return redirect(url_for("auth_bp.staff_login"))
        return f(*args, **kwargs)
    return wrapper

@records_bp.route("/records")
@login_required
def records():
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
          SELECT r.id, u.name, r.meal, r.medication, r.toilet, r.condition, r.memo, r.staff_name, r.created_at
          FROM records r JOIN users u ON r.user_id = u.id
          ORDER BY r.id DESC
        """)
        rows = c.fetchall()
    return render_template("records.html", rows=rows)

@records_bp.route("/add_record", methods=["GET","POST"])
@login_required
def add_record():
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name FROM users ORDER BY id")
        users = c.fetchall()

    MEAL_CHOICES = T[get_lang()]["meal_choices"]
    MEDICATION_CHOICES = T[get_lang()]["med_choices"]
    TOILET_CHOICES = T[get_lang()]["toilet_choices"]
    CONDITION_CHOICES = T[get_lang()]["cond_choices"]

    if request.method == "POST":
        def picked(val, other):
            other = (other or "").strip()
            return other if (val in ("その他","Other") and other) else val

        user_id = request.form.get("user_id")
        meal = picked(request.form.get("meal"), request.form.get("meal_other"))
        medication = picked(request.form.get("medication"), request.form.get("medication_other"))
        toilet = picked(request.form.get("toilet"), request.form.get("toilet_other"))
        condition = picked(request.form.get("condition"), request.form.get("condition_other"))
        memo = request.form.get("memo")
        staff_name = session.get("staff_name")

        with get_conn() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO records(user_id,meal,medication,toilet,condition,memo,staff_name)
                VALUES(?,?,?,?,?,?,?)
            """,(user_id,meal,medication,toilet,condition,memo,staff_name))
            conn.commit()
        flash(_("rec_saved"))
        return redirect(url_for("records_bp.records"))

    return render_template(
        "add_record.html",
        users=users,
        MEAL_CHOICES=MEAL_CHOICES,
        MEDICATION_CHOICES=MEDICATION_CHOICES,
        TOILET_CHOICES=TOILET_CHOICES,
        CONDITION_CHOICES=CONDITION_CHOICES
    )
