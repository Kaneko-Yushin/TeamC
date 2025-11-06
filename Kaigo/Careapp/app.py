# app.py  差し替え版（Flask + SQLite / 既存機能を壊さない最小構成）
# - /             : トップ
# - /favicon.ico  : 無ければ204で返して500を防ぐ
# - /staff_login  : GET/POST（demo/demoでログイン可・DBのusersでもOK）
# - /records      : 介護記録一覧（JOINで staff_name/resident_name を正しく取得）
# - /handover     : 引継ぎ一覧
# - /handover/new : 引継ぎ追加
# - /handover/toggle/<id> : 既読/未読トグル
#
# 依存: Flask, SQLAlchemy, python-dotenv
# DB: db/app.db（schema.sql と seed.sql を自動適用）

from __future__ import annotations
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, send_from_directory, abort, jsonify
)
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from dotenv import load_dotenv
import os
import pathlib

# ------------------------------
# 基本設定
# ------------------------------
load_dotenv()
APP_ROOT = pathlib.Path(__file__).resolve().parent
TEMPLATES_DIR = APP_ROOT / "templates"
STATIC_DIR = APP_ROOT / "static"  # 必要なら使用
FRONTEND_DIR = APP_ROOT / "frontend"  # 旧構成に合わせて静的配信したい場合に使う

app = Flask(__name__, template_folder=str(TEMPLATES_DIR))
app.secret_key = os.getenv("FLASK_SECRET", "change_me_dev_secret")

# SQLite（既存の .env に DATABASE_URL があればそちらを優先）
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(APP_ROOT / 'db' / 'app.db').as_posix()}")
engine = create_engine(DATABASE_URL, future=True)

# ------------------------------
# スキーマ適用（無ければ作る）
# ------------------------------
def ensure_schema():
    (APP_ROOT / "db").mkdir(parents=True, exist_ok=True)
    schema_path = APP_ROOT / "db" / "schema.sql"
    seed_path = APP_ROOT / "db" / "seed.sql"

    # すでに users があればスキップするが、無ければ schema/seed を流す
    with engine.begin() as conn:
        try:
            conn.execute(text("SELECT 1 FROM users LIMIT 1"))
            has_users = True
        except Exception:
            has_users = False

        if not has_users and schema_path.exists():
            conn.exec_driver_sql(schema_path.read_text(encoding="utf-8"))
            if seed_path.exists():
                conn.exec_driver_sql(seed_path.read_text(encoding="utf-8"))

        # handover_notes は存在しなくても動くように保険で作成
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS handover_notes (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              event_time TEXT NOT NULL,
              staff_id INTEGER NOT NULL,
              resident_id INTEGER,
              note TEXT NOT NULL,
              is_read INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """))

ensure_schema()

# ------------------------------
# ユーティリティ
# ------------------------------
def login_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("staff_login"))
        return fn(*args, **kwargs)
    return wrapper

# ------------------------------
# ルート
# ------------------------------
@app.get("/")
def index():
    # テンプレがあればそれを使う。無ければ簡易ページ。
    tpl = TEMPLATES_DIR / "index.html"
    if tpl.exists():
        return render_template("index.html")
    return "<h1>デジタル介護日誌</h1><p><a href='/staff_login'>スタッフログイン</a> | <a href='/handover'>引継ぎ</a> | <a href='/records'>記録</a></p>"

@app.get("/favicon.ico")
def favicon():
    # 置いてなければ 204（空）で返して 500 を防止
    fav_front = FRONTEND_DIR / "favicon.ico"
    fav_static = STATIC_DIR / "favicon.ico"
    if fav_front.exists():
        return send_from_directory(str(FRONTEND_DIR), "favicon.ico")
    if fav_static.exists():
        return send_from_directory(str(STATIC_DIR), "favicon.ico")
    return ("", 204)

# ------------------------------
# スタッフログイン
# ------------------------------
@app.route("/staff_login", methods=["GET", "POST"])
def staff_login():
    if request.method == "GET":
        tpl = TEMPLATES_DIR / "staff_login.html"
        if tpl.exists():
            return render_template("staff_login.html")
        # テンプレが無くても動く簡易フォーム
        return """
        <h2>スタッフログイン</h2>
        <form method="post">
          <input name="username" placeholder="ユーザーID" />
          <input name="password" type="password" placeholder="パスワード" />
          <button>ログイン</button>
        </form>
        """

    # POST
    username = (request.form.get("username") or "").strip()
    password = (request.form.get("password") or "").strip()

    # 1) DBにユーザーが居ればそれを優先
    with engine.begin() as conn:
        user = conn.execute(
            text("SELECT id, username FROM users WHERE username=:u AND password=:p"),
            {"u": username, "p": password},
        ).mappings().first()

    # 2) 無ければ demo/demo を許可（従来シードに合わせる）
    if not user and username == "demo" and password == "demo":
        with engine.begin() as conn:
            # users/staff に demo が無ければ作る
            conn.execute(text("""
                INSERT INTO users (username, password, role)
                SELECT :u, :p, 'staff'
                WHERE NOT EXISTS (SELECT 1 FROM users WHERE username=:u)
            """), {"u": "demo", "p": "demo"})
            demo = conn.execute(text("SELECT id FROM users WHERE username='demo'")).first()
            conn.execute(text("""
                INSERT INTO staff (user_id, name)
                SELECT :uid, '山田太郎'
                WHERE NOT EXISTS (SELECT 1 FROM staff WHERE user_id=:uid)
            """), {"uid": demo[0]})
        user = {"id": demo[0], "username": "demo"}

    if not user:
        # 失敗時はGETに戻す（テンプレがあればメッセージ表示用の設計に任せる）
        return redirect(url_for("staff_login"))

    session["user_id"] = int(user["id"])
    session["username"] = user["username"]
    return redirect(url_for("index"))

# ------------------------------
# 記録一覧
# ------------------------------
@app.get("/records")
@login_required
def records():
    try:
        with engine.begin() as conn:
            rows = conn.execute(text("""
                SELECT
                  r.id,
                  r.event_time,
                  COALESCE(r.note,'') AS note,
                  s.name  AS staff_name,
                  res.name AS resident_name
                FROM care_records r
                LEFT JOIN staff s     ON s.id  = r.staff_id
                LEFT JOIN residents res ON res.id = r.resident_id
                ORDER BY r.event_time DESC
                LIMIT 100
            """)).mappings().all()
        # テンプレがあれば使う。無ければJSONで返す。
        tpl = TEMPLATES_DIR / "records.html"
        if tpl.exists():
            return render_template("records.html", rows=rows)
        return jsonify({"records": [dict(r) for r in rows]})
    except OperationalError as e:
        return jsonify({"error": f"DB error: {str(e)}"}), 500

# ------------------------------
# 引継ぎ（handover）
# ------------------------------
@app.get("/handover")
@login_required
def handover():
    with engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT hn.id,
                   hn.event_time,
                   COALESCE(hn.note,'') AS note,
                   hn.is_read,
                   s.name  AS staff_name,
                   res.name AS resident_name
            FROM handover_notes hn
            LEFT JOIN staff s       ON s.id  = hn.staff_id
            LEFT JOIN residents res ON res.id = hn.resident_id
            ORDER BY hn.event_time DESC, hn.id DESC
            LIMIT 300
        """)).mappings().all()

    tpl = TEMPLATES_DIR / "handover.html"
    if tpl.exists():
        return render_template("handover.html", rows=rows, today=None)
    # テンプレが無い場合の簡易表示
    html_rows = "".join(
        f"<tr class='{'read' if r['is_read'] else 'unread'}'>"
        f"<td>{'既読' if r['is_read'] else '未読'}</td>"
        f"<td>{r['note']}</td>"
        f"<td>{r['event_time']}</td>"
        f"<td>{r.get('staff_name') or '-'}</td>"
        f"<td>{r.get('resident_name') or '-'}</td>"
        f"<td><form method='post' action='/handover/toggle/{r['id']}'><button>切替</button></form></td>"
        f"</tr>"
        for r in rows
    )
    return f"""
    <h2>引継ぎ / 申し送り</h2>
    <form method="post" action="/handover/new">
      <input name="staff_id" value="1" />
      <input name="resident_id" placeholder="利用者ID(任意)" />
      <input name="note" placeholder="内容" required />
      <button>追加</button>
    </form>
    <table border="1" cellpadding="6">
      <tr><th>状態</th><th>内容</th><th>時刻</th><th>担当</th><th>利用者</th><th></th></tr>
      {html_rows}
    </table>
    """

@app.post("/handover/new")
@login_required
def handover_new():
    f = request.form
    staff_id = int(f.get("staff_id") or 1)
    resident_id = f.get("resident_id") or None
    note = (f.get("note") or "").strip()
    if not note:
        return redirect(url_for("handover"))
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO handover_notes (event_time, staff_id, resident_id, note, is_read)
            VALUES (datetime('now'), :staff_id, :resident_id, :note, 0)
        """), {"staff_id": staff_id, "resident_id": resident_id, "note": note})
    return redirect(url_for("handover"))

@app.post("/handover/toggle/<int:note_id>")
@login_required
def handover_toggle(note_id: int):
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE handover_notes
            SET is_read = CASE is_read WHEN 1 THEN 0 ELSE 1 END
            WHERE id = :id
        """), {"id": note_id})
    return redirect(url_for("handover"))

# ------------------------------
# エントリポイント
# ------------------------------
if __name__ == "__main__":
    # 0.0.0.0 は待受。ローカル確認は http://127.0.0.1:5000/
    app.run(host="0.0.0.0", port=5000, debug=True)
