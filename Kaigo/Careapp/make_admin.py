# make_admin.py  (v2: with diagnostics)
import os, sys, sqlite3, argparse, textwrap

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.environ.get("DB_PATH") or os.path.join(APP_ROOT, "care.db")

def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def print_staff(conn, name):
    cur = conn.execute("SELECT id, name, role FROM staff WHERE name = ?", (name,))
    rows = cur.fetchall()
    if rows:
        for r in rows:
            print(f"  - id={r[0]} name={r[1]} role={r[2]}")
    else:
        print("  (一致するスタッフが見つかりません)")

def main():
    p = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent(
            """\
            指定スタッフを admin に昇格します。見つからなければ作成します。
            例:  python make_admin.py 鈴木
                 python make_admin.py 鈴木 --password 1234
                 python make_admin.py 鈴木 --db C:\\path\\to\\care.db
            """))
    p.add_argument("name", help="スタッフ名（完全一致）")
    p.add_argument("--password", "-p", default="admin", help="新規作成時/上書き時のパスワード（既定: admin）")
    p.add_argument("--db", default=DEFAULT_DB, help=f"DBパス（既定: {DEFAULT_DB}）")
    p.add_argument("--update-password", action="store_true", help="既存ユーザーのパスワードも指定値で上書きする")
    args = p.parse_args()

    db_path = os.path.abspath(args.db)
    print(f"[INFO] DB: {db_path}")
    print(f"[INFO] 対象: '{args.name}'（大小/全角半角も完全一致）")

    if not os.path.exists(db_path):
        print("[ERROR] DBが見つかりません。パスを確認してください。")
        sys.exit(1)

    conn = connect(db_path)
    try:
        # 事前確認
        print("[BEFORE] 状態:")
        print_staff(conn, args.name)

        cur = conn.execute("SELECT id FROM staff WHERE name = ?", (args.name,))
        row = cur.fetchone()
        if row:
            if args.update_password:
                conn.execute("UPDATE staff SET role='admin', password=? WHERE name=?",
                             (args.password, args.name))
                print(f"[OK] 既存スタッフを admin に昇格し、パスワードも更新しました。")
            else:
                conn.execute("UPDATE staff SET role='admin' WHERE name=?", (args.name,))
                print(f"[OK] 既存スタッフを admin に昇格しました。")
        else:
            conn.execute(
                "INSERT INTO staff(name, password, role) VALUES (?,?,?)",
                (args.name, args.password, "admin")
            )
            print(f"[OK] 新規 admin を作成: {args.name} / {args.password}")

        conn.commit()

        # 事後確認
        print("[AFTER] 状態:")
        print_staff(conn, args.name)

        # DB内のadmin数も表示
        cur = conn.execute("SELECT COUNT(*) FROM staff WHERE role='admin'")
        print(f"[INFO] admin ユーザー数: {cur.fetchone()[0]}")

        print("\n[NOTE] 変更を反映するには、ブラウザで一度ログアウトして再ログインしてください。")

    finally:
        conn.close()

if __name__ == "__main__":
    main()
