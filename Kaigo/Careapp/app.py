from flask import Flask, render_template, request, redirect, send_file
import sqlite3
import qrcode
import io

app = Flask(__name__)

# --- DB初期化 ---
def init_db():
    conn = sqlite3.connect("care.db")
    c = conn.cursor()

    # 利用者テーブル
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    age INTEGER,
                    gender TEXT,
                    notes TEXT
                )''')

    # 記録テーブル
    c.execute('''CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    meal TEXT,
                    medication TEXT,
                    toilet TEXT,
                    condition TEXT,
                    memo TEXT,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )''')

    # ✅ 追加：スタッフテーブル（QRログイン用）
    c.execute('''CREATE TABLE IF NOT EXISTS staff (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    role TEXT,
                    login_token TEXT
                )''')

    conn.commit()
    conn.close()

init_db()

# --- ホーム（メニュー） ---
@app.route("/")
def home():
    return render_template("home.html")

# --- 利用者一覧 ---
@app.route("/users")
def users_page():
    conn = sqlite3.connect("care.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users")
    users = c.fetchall()
    conn.close()
    return render_template("users.html", users=users)

# --- 利用者登録 ---
@app.route("/add_user", methods=["GET", "POST"])
def add_user():
    if request.method == "POST":
        name = request.form.get("name")
        age = request.form.get("age")
        gender = request.form.get("gender")
        notes = request.form.get("notes")

        conn = sqlite3.connect("care.db")
        c = conn.cursor()
        c.execute("INSERT INTO users (name, age, gender, notes) VALUES (?, ?, ?, ?)",
                  (name, age, gender, notes))
        conn.commit()
        conn.close()
        return redirect("/users")
    return render_template("add_user.html")

# --- 記録入力 ---
@app.route("/add_record", methods=["GET", "POST"])
def add_record():
    conn = sqlite3.connect("care.db")
    c = conn.cursor()
    c.execute("SELECT id, name FROM users")
    users = c.fetchall()
    conn.close()

    if request.method == "POST":
        user_id = request.form.get("user_id")
        meal = request.form.get("meal")
        medication = request.form.get("medication")
        toilet = request.form.get("toilet")
        condition = request.form.get("condition")
        memo = request.form.get("memo")

        conn = sqlite3.connect("care.db")
        c = conn.cursor()
        c.execute("INSERT INTO records (user_id, meal, medication, toilet, condition, memo) VALUES (?, ?, ?, ?, ?, ?)",
                  (user_id, meal, medication, toilet, condition, memo))
        conn.commit()
        conn.close()
        return redirect("/records")

    return render_template("add_record.html", users=users)

# --- 記録一覧 ---
@app.route("/records")
def records():
    conn = sqlite3.connect("care.db")
    c = conn.cursor()
    c.execute('''SELECT records.id, users.name, meal, medication, toilet, condition, memo
                 FROM records
                 JOIN users ON records.user_id = users.id
                 ORDER BY records.id DESC''')
    rows = c.fetchall()
    conn.close()
    return render_template("records.html", rows=rows)

# ✅ --- QRコード生成ルート ---
@app.route("/qr/<staff_name>")
def generate_qr(staff_name):
    """
    指定されたスタッフ名でQRコードを生成して返す
    例: /qr/山田 で山田さんのログインQRを出力
    """
    login_url = f"http://127.0.0.1:5000/login/{staff_name}"  # ログインURL仮設定
    img = qrcode.make(login_url)

    # メモリ上に画像を保存
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

if __name__ == "__main__":
    app.run(debug=True)
