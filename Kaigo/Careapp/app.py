from flask import Flask, render_template, request, redirect, url_for, flash, session, g
import sqlite3
import qrcode
import io
import base64

app = Flask(__name__)
app.secret_key = "secret-key"

# ---------- データベース ----------
DB_NAME = "careapp.db"

def get_db():
    conn = sqlite3.connect(DB_NAME)
    return conn

# ---------- 多言語翻訳 ----------
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

# ---------- 認証 ----------
@app.before_request
def load_logged_in_user():
    g.user = session.get("user")

@app.route("/logout")
def logout():
    session.clear()
    flash("ログアウトしました")
    return redirect(url_for("home"))

# ---------- ホーム ----------
@app.route("/")
def home():
    return render_template("home.html")

# ---------- スタッフログイン ----------
@app.route("/staff_login", methods=["GET", "POST"])
def staff_login():
    if request.method == "POST":
        name = request.form["name"]
        role = request.form.get("role", "staff")
        session["user"] = {"name": name, "role": role}
        flash(f"{name} さんでログインしました。")
        return redirect(url_for("home"))
    return render_template("staff_login.html")

# ---------- 管理ページ ----------
@app.route("/admin")
def admin_page():
    if not g.user:
        return redirect(url_for("staff_login"))
    return render_template("admin.html")

# ---------- 利用者一覧 ----------
@app.route("/users")
def users_page():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, age INTEGER, gender TEXT, room TEXT, note TEXT)")
    cur.execute("SELECT * FROM users")
    users = cur.fetchall()
    conn.close()
    return render_template("users.html", users=users)

# ---------- 利用者追加 ----------
@app.route("/add_user", methods=["GET", "POST"])
def add_user():
    if request.method == "POST":
        name = request.form["name"]
        age = request.form["age"]
        gender = request.form["gender"]
        room = request.form["room"]
        note = request.form["note"]
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO users (name, age, gender, room, note) VALUES (?, ?, ?, ?, ?)",
                    (name, age, gender, room, note))
        conn.commit()
        conn.close()
        flash("利用者を登録しました。")
        return redirect(url_for("users_page"))
    return render_template("add_user.html")

# ---------- 記録一覧 ----------
@app.route("/records")
def records():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS records (id INTEGER PRIMARY KEY AUTOINCREMENT, meal TEXT, medication TEXT, toilet TEXT, condition TEXT)")
    cur.execute("SELECT * FROM records")
    rows = cur.fetchall()
    conn.close()
    return render_template("records.html", rows=rows)

# ---------- 記録追加 ----------
@app.route("/add_record", methods=["GET", "POST"])
def add_record():
    if request.method == "POST":
        meal = request.form["meal"]
        medication = request.form["medication"]
        toilet = request.form["toilet"]
        condition = request.form["condition"]
        conn = get_db()
        cur = conn.cursor()
        cur.execute("INSERT INTO records (meal, medication, toilet, condition) VALUES (?, ?, ?, ?)",
                    (meal, medication, toilet, condition))
        conn.commit()
        conn.close()
        flash("記録を保存しました。")
        return redirect(url_for("records"))
    return render_template("add_record.html")

# ---------- スタッフ一覧 ----------
@app.route("/staff_list")
def staff_list():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS staff (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, role TEXT, qr TEXT)")
    cur.execute("SELECT * FROM staff")
    staff = cur.fetchall()
    conn.close()
    return render_template("staff_list.html", staff_list=staff)

# ---------- QR発行 ----------
@app.route("/generate_qr")
def generate_qr():
    name = g.user["name"] if g.user else "guest"
    qr_data = f"http://127.0.0.1:5000/login/{name}"
    img = qrcode.make(qr_data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return render_template("generate_qr.html", qr_code=qr_b64, name=name)

# ---------- エントリポイント ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True)
