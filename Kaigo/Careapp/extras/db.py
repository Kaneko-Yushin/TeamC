import sqlite3
import os

DB_PATH = "care.db"

def get_conn():
    return sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)

def init_db():
    first = not os.path.exists(DB_PATH)
    with get_conn() as conn:
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS users(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT,
              age INTEGER,
              gender TEXT,
              room_number TEXT,
              notes TEXT
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS records(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER,
              meal TEXT,
              medication TEXT,
              toilet TEXT,
              condition TEXT,
              memo TEXT,
              staff_name TEXT,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY(user_id) REFERENCES users(id)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS staff(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT UNIQUE,
              password TEXT,
              role TEXT,
              login_token TEXT
            )
        """)
        c.execute("""
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

        # 既存 DB の不足カラムを補修
        try:
            c.execute("SELECT room_number, notes FROM users LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE users ADD COLUMN room_number TEXT")
            c.execute("ALTER TABLE users ADD COLUMN notes TEXT")
            conn.commit()
