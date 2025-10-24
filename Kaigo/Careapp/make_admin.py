import sqlite3
import sys

DB_PATH = "care.db"

def main():
    if len(sys.argv) < 2:
        print("使い方: python make_admin.py <スタッフ名>")
        sys.exit(1)

    name = sys.argv[1]

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # レコードがなければ作る（パスワード無しのアカウント）
    c.execute("SELECT id FROM staff WHERE name=?", (name,))
    row = c.fetchone()
    if row:
        c.execute("UPDATE staff SET role='admin' WHERE id=?", (row[0],))
    else:
        c.execute("INSERT INTO staff(name, password, role, login_token) VALUES(?, NULL, 'admin', NULL)", (name,))
    conn.commit()
    conn.close()
    print(f"OK: {name} を管理者に設定しました。")

if __name__ == "__main__":
    main()
