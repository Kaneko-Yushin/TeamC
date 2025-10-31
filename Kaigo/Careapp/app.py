from flask import Flask, render_template, request, redirect, url_for, flash, session, g
import sqlite3
import qrcode
import io
import base64
from datetime import date

app = Flask(__name__)
app.secret_key = "secret-key"

# ---------- DB ----------
DB_NAME = "careapp.db"

def get_db():
    return sqlite3.connect(DB_NAME)

# ---------- i18n ----------
TR = {
    "ja": {
        "デジタル介護日誌": "デジタル介護日誌",
        "メインメニュー": "メインメニュー",
        "利用者一覧": "利用者一覧",
        "登録されている利用者を確認": "登録されている利用者を確認",
        "記録入力": "記録入力",
        "食事・服薬・排泄・体調など": "食事・服薬・排泄・体調など",
        "記録一覧": "記録一覧",
        "これまでの記録を閲覧": "これまでの記録を閲覧",
        "利用者登録": "利用者登録",
        "管理者のみ": "管理者のみ",
        "設定": "設定",
        "スタッフ・QR発行など": "スタッフ・QR発行など",
        "引継ぎ": "引継ぎ",
        "引継ぎボード": "引継ぎボード",
        "当日の申し送り・シフト別": "当日の申し送り・シフト別",
        "管理ページ": "管理ページ",
        "戻る": "戻る",
        "スタッフ一覧": "スタッフ一覧",
        "登録済みスタッフの確認と管理": "登録済みスタッフの確認と管理",
        "QR発行": "QR発行",
        "スタッフのQRログインを作成": "スタッフのQRログインを作成",
        "利用者管理": "利用者管理",
        "利用者情報の編集と確認": "利用者情報の編集と確認",
        "本日の引継ぎ": "本日の引継ぎ",
        "シフト": "シフト",
        "内容": "内容",
        "担当": "担当",
        "追加": "追加",
        "記録を追加": "記録を追加",
        "ホームに戻る": "ホームに戻る",
        "ログアウトしました": "ログアウトしました",
    },
    "en": {
        "デジタル介護日誌": "Digital Care Notes",
        "メインメニュー": "Main Menu",
        "利用者一覧": "Residents",
        "登録されている利用者を確認": "View registered residents",
        "記録入力": "Add Record",
        "食事・服薬・排泄・体調など": "Meals, Medicine, Condition etc.",
        "記録一覧": "Records",
        "これまでの記録を閲覧": "View past records",
        "利用者登録": "Add Resident",
        "管理者のみ": "(Admin only)",
        "設定": "Settings",
        "スタッフ・QR発行など": "Staff & QR Settings",
        "引継ぎ": "Handover",
        "引継ぎボード": "Handover Board",
        "当日の申し送り・シフト別": "Daily Notes & Shifts",
        "管理ページ": "Admin Page",
        "戻る": "Back",
        "スタッフ一覧": "Staff List",
        "登録済みスタッフの確認と管理": "Manage registered staff",
        "QR発行": "Issue QR",
        "スタッフのQRログインを作成": "Generate QR login for staff",
        "利用者管理": "Resident Management",
        "利用者情報の編集と確認": "Edit and view resident info",
        "本日の引継ぎ": "Today's Handover",
        "シフト": "Shift",
        "内容": "Note",
        "担当": "Staff",
        "追加": "Add",
        "記録を追加": "Add Record",
        "ホームに戻る": "Back to Home",
        "ログアウトしました": "Logged out",
    },
}

def _(text):
    lang = session.get("lang", "ja")
    return TR.get(lang, {}).get(text, text)

@app.context_processor
def inject_lang():
    return {"_": _, "current_lang": session.get("lang", "ja")}

@app.route("/set_language/<lang>")
def set_language(lang):
    if lang in TR:
        session["lang"] = lang
    return redirect(request.referrer or url_for("home"))

# ---------- auth ----------
@app.before_request
def load_user():
    g.user = session.get("user")

@app.route("/logout")
def logout():
    session.clear()
    flash(_("ログアウトしました"))
    return redirect(url_for("home"))

# ---------- home ----------
@app.route("/")
def home():
    return render_template("home.html")

# ---------- login ----------
@app.route("/staff_login", methods=["GET", "POST"])
def staff_login():
    if request.method == "POST":
        name = request.form["name"].strip() or "guest"
        role = request.form.get("role", "staff")
        session["user"] = {"name": name, "role": role}
        flash(f"{name} さんでログインしました。")
        return redirect(url_for("home"))
    return render_template("staff_login.html")

# ---------- admin ----------
@app.route("/admin")
def admin_page():
    if not g.user:
        return redirect(url_for("staff_login"))
    return render_template("admin.html")

# ---------- users ----------
@app.route("/users")
def users_page():
    conn = get_db(); c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, age INTEGER, gender TEXT, room TEXT, note TEXT
    )""")
    c.execute("SELECT * FROM users ORDER BY id")
    users = c.fetchall()
    conn.close()
    return render_template("users.html", users=users)

@app.route("/add_user", methods=["GET","POST"])
def add_user():
    if request.method == "POST":
        name = request.form["name"]; age = request.form["age"]
        gender = request.form["gender"]; room = request.form["room"]
        note = request.form["note"]
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT INTO users(name,age,gender,room,note) VALUES(?,?,?,?,?)",
                  (name, age, gender, room, note))
        conn.commit(); conn.close()
        flash("利用者を登録しました。")
        return redirect(url_for("users_page"))
    return render_template("add_user.html")

# ---------- records ----------
@app.route("/records")
def records():
    conn = get_db(); c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS records(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        meal TEXT, medication TEXT, toilet TEXT, condition TEXT, created DATE DEFAULT CURRENT_DATE
    )""")
    c.execute("SELECT id, meal, medication, toilet, condition, created FROM records ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return render_template("records.html", rows=rows)

@app.route("/add_record", methods=["GET","POST"])
def add_record():
    if request.method == "POST":
        meal = request.form["meal"]
        medication = request.form["medication"]
        toilet = request.form["toilet"]
        condition = request.form["condition"]
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT INTO records(meal,medication,toilet,condition) VALUES(?,?,?,?)",
                  (meal, medication, toilet, condition))
        conn.commit(); conn.close()
        flash("記録を保存しました。")
        return redirect(url_for("records"))
    return render_template("add_record.html")

# ---------- staff ----------
@app.route("/staff_list")
def staff_list():
    conn = get_db(); c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS staff(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT, role TEXT, qr TEXT
    )""")
    c.execute("SELECT * FROM staff ORDER BY id")
    staff = c.fetchall()
    conn.close()
    return render_template("staff_list.html", staff_list=staff)

@app.route("/generate_qr")
def generate_qr():
    if not g.user:
        return redirect(url_for("staff_login"))
    name = g.user["name"]
    qr_data = f"http://127.0.0.1:5000/login/{name}"
    img = qrcode.make(qr_data)
    buf = io.BytesIO(); img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return render_template("generate_qr.html", qr_code=qr_b64, name=name)

# ---------- handover (★追加) ----------
@app.route("/handover", methods=["GET", "POST"])
def handover():
    conn = get_db(); c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS handover(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        h_date TEXT, shift TEXT, note TEXT, staff TEXT
    )""")
    if request.method == "POST":
        h_date = request.form.get("h_date") or date.today().isoformat()
        shift  = request.form.get("shift","")
        note   = request.form.get("note","")
        staff  = request.form.get("staff","")
        c.execute("INSERT INTO handover(h_date,shift,note,staff) VALUES(?,?,?,?)",
                  (h_date, shift, note, staff))
        conn.commit()
        flash("引継ぎを追加しました。")
        return redirect(url_for("handover"))
    # GET
    today = date.today().isoformat()
    c.execute("SELECT id, h_date, shift, note, staff FROM handover WHERE h_date=? ORDER BY id DESC", (today,))
    rows = c.fetchall()
    conn.close()
    return render_template("handover.html", rows=rows, today=today)

# ---------- main ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
