import os
import json
from flask import session, g

# translations フォルダから {ja,en}.json を読む
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRANSLATIONS_DIR = os.path.join(BASE_DIR, "translations")

def _load(lang: str):
    path = os.path.join(TRANSLATIONS_DIR, f"{lang}.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

_cache = {
    "ja": _load("ja"),
    "en": _load("en"),
}

def get_current_lang():
    # g.current_lang は init_i18n が before_request でセット
    return getattr(g, "current_lang", None) or session.get("lang", "ja")

def translate(text: str) -> str:
    lang = get_current_lang()
    data = _cache.get(lang) or {}
    return data.get(text, text)

# Python 側でも _( ) を使えるようにエイリアス
_ = translate

def init_i18n(app):
    @app.before_request
    def _set_lang():
        g.current_lang = session.get("lang", "ja")

    # Jinja2 テンプレートで _() / current_lang が使える
    app.jinja_env.globals.update(_=translate)
    app.jinja_env.globals.update(current_lang=get_current_lang)
