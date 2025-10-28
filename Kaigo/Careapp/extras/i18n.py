# extras/i18n.py
from functools import lru_cache

LANG_MAP = {
    "ja": {
        # 共通
        "ログインが必要です。": "ログインが必要です。",
        "登録完了。ログインしてください。": "登録完了。ログインしてください。",
        "同名のスタッフがすでに存在します。": "同名のスタッフがすでに存在します。",
        "名前またはパスワードが間違っています。": "名前またはパスワードが間違っています。",
        "%s さんでログインしました。": "%s さんでログインしました。",
        "ログアウトしました。": "ログアウトしました。",
        "管理者": "管理者",

        # ホーム
        "🌿 デジタル介護日誌": "🌿 デジタル介護日誌",
        "ログイン中：%s さん": "ログイン中：%s さん",
        "👥 利用者一覧": "👥 利用者一覧",
        "📝 記録を追加": "📝 記録を追加",
        "📖 記録を見る": "📖 記録を見る",
        "ログアウト": "ログアウト",
        "🔑 スタッフログイン": "🔑 スタッフログイン",
        "＋ 新規スタッフ登録": "＋ 新規スタッフ登録",
        "⚙ 管理ページ": "⚙ 管理ページ",
        "言語": "言語",
        "日本語": "日本語",
        "English": "English",

        # スタッフ一覧
        "スタッフ一覧 - デジタル介護日誌": "スタッフ一覧 - デジタル介護日誌",
        "スタッフ一覧": "スタッフ一覧",
        "登録済みスタッフの確認と管理": "登録済みスタッフの確認と管理",
        "名前": "名前",
        "役職": "役職",
        "QRログイン": "QRログイン",
        "操作": "操作",
        "スタッフ": "スタッフ",
        "QRリンク": "QRリンク",
        "未発行": "未発行",
        "QR再発行": "QR再発行",
        "＋ QR発行（新規）": "＋ QR発行（新規）",
        "← 管理ページに戻る": "← 管理ページに戻る",
        "本当に削除しますか？": "本当に削除しますか？",

        # 利用者一覧
        "利用者一覧": "利用者一覧",
        "年齢": "年齢", "性別": "性別", "部屋番号": "部屋番号", "備考": "備考",
        "削除": "削除",
        "＋ 新しい利用者を登録": "＋ 新しい利用者を登録",
        "← ホームに戻る": "← ホームに戻る",
    },
    "en": {
        # Common
        "ログインが必要です。": "Login is required.",
        "登録完了。ログインしてください。": "Registered. Please sign in.",
        "同名のスタッフがすでに存在します。": "A staff member with the same name already exists.",
        "名前またはパスワードが間違っています。": "Incorrect name or password.",
        "%s さんでログインしました。": "Signed in as %s.",
        "ログアウトしました。": "Logged out.",
        "管理者": "Admin",

        # Home
        "🌿 デジタル介護日誌": "🌿 Digital Care Notes",
        "ログイン中：%s さん": "Signed in: %s",
        "👥 利用者一覧": "👥 Residents",
        "📝 記録を追加": "📝 Add Record",
        "📖 記録を見る": "📖 Records",
        "ログアウト": "Logout",
        "🔑 スタッフログイン": "🔑 Staff Login",
        "＋ 新規スタッフ登録": "+ New Staff",
        "⚙ 管理ページ": "⚙ Admin",
        "言語": "Language",
        "日本語": "日本語",
        "English": "English",

        # Staff list
        "スタッフ一覧 - デジタル介護日誌": "Staff List - Digital Care Notes",
        "スタッフ一覧": "Staff",
        "登録済みスタッフの確認と管理": "Review & manage registered staff",
        "名前": "Name",
        "役職": "Role",
        "QRログイン": "QR Login",
        "操作": "Actions",
        "スタッフ": "Staff",
        "QRリンク": "QR link",
        "未発行": "Not issued",
        "QR再発行": "Reissue QR",
        "＋ QR発行（新規）": "+ Issue QR (new)",
        "← 管理ページに戻る": "← Back to Admin",
        "本当に削除しますか？": "Are you sure you want to delete?",

        # Users
        "利用者一覧": "Residents",
        "年齢": "Age", "性別": "Gender", "部屋番号": "Room", "備考": "Notes",
        "削除": "Delete",
        "＋ 新しい利用者を登録": "+ Add New Resident",
        "← ホームに戻る": "← Back to Home",
    }
}

@lru_cache(maxsize=8)
def _get_table(lang: str):
    return LANG_MAP.get(lang, LANG_MAP["ja"])

def get_i18n(lang: str):
    table = _get_table(lang or "ja")
    def _(msg: str):
        return table.get(msg, msg)
    return _
