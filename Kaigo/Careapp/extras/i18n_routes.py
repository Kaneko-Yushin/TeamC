# -*- coding: utf-8 -*-
from flask import Blueprint, redirect, request, session
from urllib.parse import urlparse, urlunparse

lang_bp = Blueprint("lang", __name__, url_prefix="/i18n")

@lang_bp.get("/set")
def set_lang_get():
    # /i18n/set?lang=en&next=...
    lang = request.args.get("lang", "ja")
    session["lang"] = lang
    nxt = request.args.get("next") or "/"
    return redirect(_safe_next(nxt))

@lang_bp.post("/set")
def set_lang_post():
    lang = request.form.get("lang", "ja")
    session["lang"] = lang
    nxt = request.form.get("next") or "/"
    return redirect(_safe_next(nxt))

def _safe_next(nxt: str) -> str:
    # 同一ホスト内へのリダイレクトに限定（簡易ガード）
    try:
        p = urlparse(nxt)
        if p.netloc:  # 外部は弾く
            return "/"
        # クエリやパスは維持
        return urlunparse(("", "", p.path or "/", "", p.query, ""))
    except Exception:
        return "/"
