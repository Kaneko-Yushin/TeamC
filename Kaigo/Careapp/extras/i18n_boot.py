# -*- coding: utf-8 -*-
from flask import request, session
from flask_babel import Babel, gettext as _
import pytz

# Flask-Babel v3系想定
babel = Babel()

SUPPORTED_LANGS = {
    "ja": "日本語",
    "en": "English",
    "vi": "Tiếng Việt",
    "zh_Hans": "简体中文",
    "ko": "한국어",
}

def _locale_selector():
    # セッション > ブラウザ優先言語 > 既定: ja
    lang = session.get("lang")
    if lang in SUPPORTED_LANGS:
        return lang
    return request.accept_languages.best_match(list(SUPPORTED_LANGS.keys())) or "ja"

def attach_i18n(app):
    # 既定ロケール/タイムゾーン
    babel.init_app(
        app,
        default_locale="ja",
        default_timezone=str(pytz.timezone("Asia/Tokyo")),
        locale_selector=_locale_selector,
    )

    # Jinjaグローバル（_ をテンプレで使えるように）
    app.jinja_env.globals.update(_=_)

    # テンプレ共通で使う値（言語リスト/現在言語）
    @app.context_processor
    def inject_langs():
        return {
            "AVAILABLE_LANGS": SUPPORTED_LANGS,
            "CURRENT_LANG": session.get("lang") or "ja",
        }
