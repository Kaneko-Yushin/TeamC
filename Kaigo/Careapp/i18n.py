# i18n.py
from flask import Blueprint, session, redirect, request, url_for, current_app, g
import gettext
import os

i18n_bp = Blueprint("i18n", __name__)

SUPPORTED_LANGS = ["ja", "en"]
DEFAULT_LANG = "ja"

def get_lang():
    lang = session.get("lang") or request.accept_languages.best_match(SUPPORTED_LANGS) or DEFAULT_LANG
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG
    return lang

def _get_translator(lang):
    # translations/<lang>/LC_MESSAGES/messages.mo を読む
    localedir = os.path.join(current_app.root_path, "translations")
    try:
        trans = gettext.translation("messages", localedir=localedir, languages=[lang])
        trans.install()
        _ = trans.gettext
    except Exception:
        gettext.install("messages")
        _ = gettext.gettext
    return _

@i18n_bp.before_app_request
def inject_lang():
    g.CURRENT_LANG = get_lang()
    g._ = _get_translator(g.CURRENT_LANG)

@i18n_bp.app_context_processor
def expose_i18n():
    # テンプレで CURRENT_LANG と _() を使えるようにする
    return {"CURRENT_LANG": getattr(g, "CURRENT_LANG", DEFAULT_LANG), "_": getattr(g, "_", lambda s: s)}

@i18n_bp.route("/set_language/<lang>")
def set_language(lang):
    if lang not in SUPPORTED_LANGS:
        lang = DEFAULT_LANG
    session["lang"] = lang
    # 直前ページに戻る（なければホーム）
    ref = request.referrer or url_for("home")
    return redirect(ref)
