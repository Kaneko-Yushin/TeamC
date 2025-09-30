from flask import Flask, render_template, request, redirect
import sqlite3

app = Flask(__name__)

@app.route("/records")
def records():
    conn = sqlite3.connect("care.db")
    c = conn.cursor()
    c.execute("SELECT * FROM records ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    return render_template("records.html", rows=rows)


# --- DB初期化 ---
def init_db():
    conn = sqlite3.connect("care.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    meal TEXT,
                    medication TEXT,
                    toilet TEXT,
                    condition TEXT,
                    memo TEXT
                )''')
    conn.commit()
    conn.close()

init_db()

# --- ホーム画面（入力フォーム） ---
@app.route("/")
def index():
    return render_template("form.html")

# --- 記録保存 ---
@app.route("/save", methods=["POST"])
def save():
    meal = request.form.get("meal")
    medication = request.form.get("medication")
    toilet = request.form.get("toilet")
    condition = request.form.get("condition")
    memo = request.form.get("memo")

    conn = sqlite3.connect("care.db")
    c = conn.cursor()
    c.execute("INSERT INTO records (meal, medication, toilet, condition, memo) VALUES (?, ?, ?, ?, ?)",
              (meal, medication, toilet, condition, memo))
    conn.commit()
    conn.close()

    return redirect("/")

if __name__ == "__main__":
    app.run(debug=True)
