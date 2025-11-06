from flask import session

LANGS = ["ja", "en"]

T = {
    "ja": {
        "app_title":"デジタル介護日誌",
        "lang":"言語","ja":"日本語","en":"English",
        "login_needed":"ログインが必要です。","admin_needed":"管理者権限が必要です。",
        "hello_login":"%s さんでログインしました。","login_failed":"名前またはパスワードが間違っています。","logged_out":"ログアウトしました。",
        "dup_staff":"同名のスタッフがすでに存在します。","reg_done":"登録完了。ログインしてください。",
        "user_added":"利用者を登録しました。","user_deleted":"利用者を削除しました。","rec_saved":"記録を保存しました。","handover_added":"引継ぎを追加しました。","invalid_qr":"無効なQRコードです。",
        "home_ui_h1":"🌿 デジタル介護日誌","home_login":"ログインまたはスタッフ登録を行ってください。",
        "login_btn":"🔑 スタッフログイン","register_btn":"＋ 新規スタッフ登録",
        "logged_in_as":"ログイン中：%s","admin_page":"管理ページへ","logout":"ログアウト",
        "open_users_btn":"👥 利用者一覧","add_record_btn":"📝 記録を追加","view_records_btn":"📖 記録を見る","handover_btn":"🔄 引継ぎボード",
        "Users":"利用者一覧","name":"名前","age":"年齢","gender":"性別","room_no":"部屋番号","notes":"備考",
        "delete":"削除","really_delete":"本当に削除しますか？","new_user":"＋ 新しい利用者を登録","back_home":"← ホームに戻る",
        "Records":"記録一覧","user":"利用者","meal":"食事","medication":"服薬","toilet":"排泄","condition":"体調","memo":"メモ","staff":"職員","created_at":"作成日時","add":"追加","select_user":"利用者を選択",
        "meal_choices":["全量","8割","半分","1/3","ほぼ食べず","その他"],"med_choices":["済","一部","未","自己管理","その他"],
        "toilet_choices":["自立","誘導","介助","失禁なし","失禁あり","その他"],"cond_choices":["良好","普通","要観察","受診","発熱(37.5℃～)","その他"],"other":"その他入力","save":"保存",
        "Admin":"管理ページ","open_records":"記録管理","open_staff":"スタッフ管理","open_handover":"引継ぎへ","open_qr_issue":"QRログイン発行",
        "StaffList":"スタッフ一覧","role":"役職","qr_login":"QRログイン","qr_link":"QRリンク","not_issued":"未発行","qr_reissue":"QR再発行","delete_staff":"削除",
        "role_admin":"管理者","role_caregiver":"スタッフ","qr_new":"＋ QR発行（新規）","back_admin":"← 管理ページに戻る",
        "GenerateQR":"QRログイン発行","role_select":"役割を選択",
        "Handover":"引継ぎボード","date":"日付","shift":"シフト","resident":"利用者","priority":"優先度","title":"タイトル","body":"本文","day":"日勤","late":"遅番","night":"夜勤","apply":"適用",
    },
    "en": {
        "app_title":"Digital Care Notes",
        "lang":"Language","ja":"Japanese","en":"English",
        "login_needed":"Login required.","admin_needed":"Admin privileges required.",
        "hello_login":"Logged in as %s.","login_failed":"Incorrect name or password.","logged_out":"Logged out.",
        "dup_staff":"A staff member with the same name already exists.","reg_done":"Registration completed. Please log in.",
        "user_added":"Resident added.","user_deleted":"Resident deleted.","rec_saved":"Record saved.","handover_added":"Handover added.","invalid_qr":"Invalid QR code.",
        "home_ui_h1":"🌿 Digital Care Notes","home_login":"Please log in or register.",
        "login_btn":"🔑 Staff Login","register_btn":"+ New Staff Registration",
        "logged_in_as":"Signed in: %s","admin_page":"Go to Admin","logout":"Log out",
        "open_users_btn":"👥 Residents","add_record_btn":"📝 Add Record","view_records_btn":"📖 View Records","handover_btn":"🔄 Handover Board",
        "Users":"Residents","name":"Name","age":"Age","gender":"Gender","room_no":"Room No.","notes":"Notes",
        "delete":"Delete","really_delete":"Are you sure to delete?","new_user":"+ Add new resident","back_home":"← Back to Home",
        "Records":"Records","user":"Resident","meal":"Meal","medication":"Medication","toilet":"Toilet","condition":"Condition","memo":"Memo","staff":"Staff","created_at":"Created At","add":"Add","select_user":"Select resident",
        "meal_choices":["All","80%","Half","One third","Barely","Other"],"med_choices":["Done","Partial","Not yet","Self","Other"],
        "toilet_choices":["Independent","Guided","Assisted","No incontinence","Incontinence","Other"],"cond_choices":["Good","Normal","Watch","Visit doctor","Fever (37.5℃~)","Other"],"other":"Other text","save":"Save",
        "Admin":"Admin","open_records":"Records","open_staff":"Staff","open_handover":"Handover","open_qr_issue":"QR Issue",
        "StaffList":"Staff List","role":"Role","qr_login":"QR Login","qr_link":"QR link","not_issued":"Not issued","qr_reissue":"Re-issue QR","delete_staff":"Delete",
        "role_admin":"Admin","role_caregiver":"Caregiver","qr_new":"+ New QR Issue","back_admin":"← Back to Admin",
        "GenerateQR":"QR Issue","role_select":"Select role",
        "Handover":"Handover Board","date":"Date","shift":"Shift","resident":"Resident","priority":"Priority","title":"Title","body":"Body","day":"Day","late":"Late","night":"Night","apply":"Apply",
    }
}

def get_lang():
    lang = session.get("lang")
    return lang if lang in LANGS else "ja"

def _(key):
    lang = get_lang()
    val = T.get(lang, {}).get(key)
    return val if val is not None else key

def init_i18n(app):
    @app.context_processor
    def inject_i18n():
        return {"_": _, "current_lang": get_lang(), "LANGS": LANGS}
