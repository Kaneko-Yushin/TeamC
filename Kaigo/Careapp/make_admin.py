# make_admin.py
import os, sys, sqlite3

APP_ROOT = os.path.dirname(__file__)
DB_PATH = os.environ.get("DB_PATH") or os.path.join(APP_ROOT, "care.db")

def main():
    if len(sys.argv) < 2:
        print("使い方: python make_admin.py <スタッフ名> [パスワード]")
        return
    name = sys.argv[1]
    password = sys.argv[2] if len(sys.argv) >= 3 else "admin"

    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON;")
        cur.execute("SELECT id FROM staff WHERE name=?", (name,))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE staff SET role='admin' WHERE name=?", (name,))
            print(f"[OK] 既存スタッフ「{name}」を admin に昇格")
        else:
            cur.execute(
                "INSERT INTO staff(name, password, role) VALUES(?,?,?)",
                (name, password, "admin"),
            )
            print(f"[OK] 新規に admin を作成: {name} / {password}")
        conn.commit()
    finally:
        conn.close()

if __name__ == "__main__":
    main()
