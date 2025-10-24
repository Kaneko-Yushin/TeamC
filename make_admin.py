# make_admin.py
import sqlite3, sys
DB = "care.db"

if len(sys.argv) < 2:
    print("使い方: python make_admin.py <スタッフ名>")
    raise SystemExit(1)

name = sys.argv[1]
conn = sqlite3.connect(DB)
cur = conn.cursor()
cur.execute("UPDATE staff SET role='管理者' WHERE name=?", (name,))
if cur.rowcount == 0:
    cur.execute("INSERT INTO staff (name, password, role) VALUES (?, ?, ?)", (name, "temp", "管理者"))
conn.commit()
cur.execute("SELECT id, name, role FROM staff WHERE name=?", (name,))
print("更新結果:", cur.fetchone())
conn.close()
print("OK: 管理者にしました。")
