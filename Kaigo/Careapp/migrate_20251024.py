# migrate_20251024.py
import sqlite3, os

DB_PATH = "care.db"

def colset(conn, table):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return {r[1] for r in cur.fetchall()}

def add_col(conn, table, col, decl):
    cs = colset(conn, table)
    if col not in cs:
        print(f"[{table}] add column: {col} {decl}")
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")

def ensure_tables(conn):
    cur = conn.cursor()
    # users
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT,
          age INTEGER,
          gender TEXT
        )
    """)
    # records
    cur.execute("""
        CREATE TABLE IF NOT EXISTS records(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER,
          meal TEXT,
          medication TEXT,
          toilet TEXT,
          condition TEXT,
          memo TEXT,
          staff_name TEXT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # staff
    cur.execute("""
        CREATE TABLE IF NOT EXISTS staff(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT UNIQUE,
          password TEXT,
          role TEXT,
          login_token TEXT
        )
    """)
    # handover
    cur.execute("""
        CREATE TABLE IF NOT EXISTS handover(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          on_date TEXT,
          shift TEXT,
          resident_id INTEGER,
          priority INTEGER,
          title TEXT,
          body TEXT,
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

def migrate(conn):
    # users に不足しがちな列を追加
    add_col(conn, "users", "room_number", "TEXT")
    add_col(conn, "users", "notes", "TEXT")

    # records
    for col, decl in [
        ("meal", "TEXT"),
        ("medication", "TEXT"),
        ("toilet", "TEXT"),
        ("condition", "TEXT"),
        ("memo", "TEXT"),
        ("staff_name", "TEXT"),
        ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ]:
        add_col(conn, "records", col, decl)

    # staff
    for col, decl in [
        ("password", "TEXT"),
        ("role", "TEXT"),
        ("login_token", "TEXT"),
    ]:
        add_col(conn, "staff", col, decl)

    # handover
    for col, decl in [
        ("on_date", "TEXT"),
        ("shift", "TEXT"),
        ("resident_id", "INTEGER"),
        ("priority", "INTEGER"),
        ("title", "TEXT"),
        ("body", "TEXT"),
        ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ]:
        add_col(conn, "handover", col, decl)

    conn.commit()

def main():
    if not os.path.exists(DB_PATH):
        print("care.db が見つかりません。アプリ起動後に作られるDBに対して実行してください。")
        return
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    try:
        ensure_tables(conn)
        migrate(conn)
        print("✅ マイグレーション完了！")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
