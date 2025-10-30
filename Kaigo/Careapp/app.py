from flask import Flask, redirect, url_for, session
from extras.db import init_db
from extras.i18n import init_i18n, LANGS

# Blueprints
from extras.auth import auth_bp
from extras.users_bp import users_bp
from extras.records_bp import records_bp
from extras.handover_bp import handover_bp
from extras.staff_admin import staff_admin_bp

import secrets

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

# DB 初期化（不足カラムも補修）
init_db()

# i18n 注入
init_i18n(app)

# Blueprints 登録
app.register_blueprint(auth_bp)
app.register_blueprint(users_bp)
app.register_blueprint(records_bp)
app.register_blueprint(handover_bp)
app.register_blueprint(staff_admin_bp)

@app.route("/")
def home():
    from flask import render_template
    return render_template("home.html")

@app.route("/set_language/<lang>")
def set_language(lang):
    if lang in LANGS:
        session["lang"] = lang
    return redirect(url_for("home"))

if __name__ == "__main__":
    # 管理者が0なら通知だけ（自動作成はしない）
    from extras.db import get_conn
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM staff WHERE role='admin'")
        if c.fetchone()[0] == 0:
            print("※ 管理者が未登録です。管理者を作成/昇格してください（QR発行など）。")
    app.run(host="0.0.0.0", port=5000, debug=True)
