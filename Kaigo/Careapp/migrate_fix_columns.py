# migrate_fix_columns.py
import sqlite3, os

DB_PATH = "care.db"

def col_exists(cur, table, col):
    cur.execute(f"PRAGMA table_info({table})")
    return any(r[1] == col for r in cur.fetchall())

with sqlite3.connect(DB_PATH) as conn:
    c = conn.cursor()

    # handover に h_date が無ければ追加
    if not col_exists(c, "handover", "h_date"):
        c.execute("ALTER TABLE handover ADD COLUMN h_date TEXT")
        # on_date があれば中身をコピー
        if col_exists(c, "handover", "on_date"):
            c.execute("UPDATE handover SET h_date = on_date")
        conn.commit()

    # handover に staff / note が無ければ追加
    if not col_exists(c, "handover", "staff"):
        c.execute("ALTER TABLE handover ADD COLUMN staff TEXT")
    if not col_exists(c, "handover", "note"):
        c.execute("ALTER TABLE handover ADD COLUMN note TEXT")
    conn.commit()

print("✅ OK: migrate_fix_columns done")
