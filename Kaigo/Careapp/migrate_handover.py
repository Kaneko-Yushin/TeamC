import sqlite3

DB_PATH = "care.db"

def run():
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    c = conn.cursor()

    # テーブルが無ければ作る
    c.execute("""
        CREATE TABLE IF NOT EXISTS handover (
            id INTEGER PRIMARY KEY AUTOINCREMENT
        )
    """)
    c.execute("PRAGMA table_info(handover)")
    existing = {row[1] for row in c.fetchall()}

    cols = [
        ("on_date",     "TEXT"),
        ("shift",       "TEXT"),
        ("resident_id", "INTEGER"),
        ("priority",    "INTEGER DEFAULT 2"),
        ("title",       "TEXT"),
        ("content",     "TEXT"),
        ("created_by",  "TEXT"),
        ("created_at",  "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("updated_at",  "TIMESTAMP"),
    ]
    for col, ddl in cols:
        if col not in existing:
            try:
                c.execute(f"ALTER TABLE handover ADD COLUMN {col} {ddl}")
                print(f"ADD COLUMN {col} {ddl} ✔")
            except sqlite3.OperationalError as e:
                print(f"ADD COLUMN {col} -> skip ({e})")

    c.execute("CREATE INDEX IF NOT EXISTS idx_handover_on_date ON handover(on_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_handover_shift ON handover(shift)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_handover_resident ON handover(resident_id)")

    conn.commit()
    conn.close()
    print("Migration done ✔")

if __name__ == "__main__":
    run()
