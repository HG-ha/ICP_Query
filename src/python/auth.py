# -*- coding: utf-8 -*-
"""账号鉴权：HMAC 会话 Cookie / Bearer Token"""
import base64
import hashlib
import hmac
import json
import time
from typing import Optional

from load_config import config

COOKIE_NAME = "ymicp_session"
HASH_PREFIX = "sha256$"


def _auth_cfg():
    return getattr(config, "auth", None)


def auth_enabled() -> bool:
    a = _auth_cfg()
    return bool(a and getattr(a, "enable", False))


def _secret() -> bytes:
    a = _auth_cfg()
    secret = (getattr(a, "secret", None) or "change-me").encode("utf-8")
    return secret


def _session_hours() -> int:
    a = _auth_cfg()
    try:
        return int(getattr(a, "session_hours", 72) or 72)
    except Exception:
        return 72


def hash_password(plain: str) -> str:
    dig = hashlib.sha256(plain.encode("utf-8")).hexdigest()
    return f"{HASH_PREFIX}{dig}"


def verify_password(stored: str, plain: str) -> bool:
    if not stored or plain is None:
        return False
    if stored.startswith(HASH_PREFIX):
        return hmac.compare_digest(stored, hash_password(plain))
    return hmac.compare_digest(stored, plain)


def find_user(username: str):
    a = _auth_cfg()
    users = getattr(a, "users", None) or []
    for u in users:
        if isinstance(u, dict):
            uname = u.get("username")
            pwd = u.get("password")
        else:
            uname = getattr(u, "username", None)
            pwd = getattr(u, "password", None)
        if uname == username:
            return uname, pwd
    return None, None


def authenticate(username: str, password: str) -> bool:
    uname, stored = find_user(username)
    if not uname:
        return False
    return verify_password(str(stored), password)


def create_token(username: str) -> str:
    exp = int(time.time()) + _session_hours() * 3600
    payload = json.dumps({"u": username, "e": exp}, separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    sig = hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_token(token: str) -> Optional[str]:
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    expect = hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, sig):
        return None
    try:
        pad = "=" * (-len(body) % 4)
        raw = base64.urlsafe_b64decode(body + pad)
        data = json.loads(raw.decode("utf-8"))
        if int(data.get("e", 0)) < int(time.time()):
            return None
        username = data.get("u")
        if not username:
            return None
        uname, _ = find_user(username)
        if not uname:
            return None
        return username
    except Exception:
        return None


def extract_token_from_request(request) -> Optional[str]:
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(COOKIE_NAME)


def resolve_user(request) -> Optional[str]:
    if not auth_enabled():
        return None
    token = extract_token_from_request(request)
    if not token:
        return None
    return verify_token(token)


def is_public_path(path: str, method: str = "GET") -> bool:
    if path.startswith("/static/"):
        return True
    if path in ("/api/auth/login", "/api/auth/status"):
        return True
    # 放行首页 HTML，由前端根据 /api/auth/status 展示登录框
    if path in ("/", "") and method.upper() == "GET":
        return True
    return False


def maybe_hash_users_in_config_dict(config_dict: dict) -> dict:
    """保存配置时将明文密码转为 sha256$"""
    auth = config_dict.get("auth") or {}
    users = auth.get("users") or []
    new_users = []
    for u in users:
        if not isinstance(u, dict):
            continue
        pwd = u.get("password") or ""
        item = {"username": u.get("username", ""), "password": pwd}
        if pwd and not str(pwd).startswith(HASH_PREFIX):
            item["password"] = hash_password(str(pwd))
        new_users.append(item)
    if "auth" in config_dict:
        config_dict["auth"]["users"] = new_users
    return config_dict
