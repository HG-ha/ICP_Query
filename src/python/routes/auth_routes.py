# -*- coding: utf-8 -*-
"""认证相关 API"""
from aiohttp import web
from middlewares import jsondump, wj
from auth import (
    COOKIE_NAME,
    auth_enabled,
    authenticate,
    create_token,
    resolve_user,
    _session_hours,
)


routes = web.RouteTableDef()


@jsondump
@routes.view(r"/api/auth/status")
async def auth_status(request):
    enabled = auth_enabled()
    user = resolve_user(request) if enabled else None
    return wj({
        "code": 200,
        "data": {
            "enable": enabled,
            "authenticated": (not enabled) or bool(user),
            "username": user,
        },
    })


@routes.view(r"/api/auth/login")
async def auth_login(request):
    if request.method != "POST":
        return wj({"code": 405, "message": "Method Not Allowed"})
    if not auth_enabled():
        return wj({"code": 200, "message": "认证未启用", "data": {"enable": False}})

    data = await request.json()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return wj({"code": 400, "message": "请输入用户名和密码"})
    if not authenticate(username, password):
        return wj({"code": 401, "message": "用户名或密码错误"})

    token = create_token(username)
    # 不使用 jsondump，避免丢失 Set-Cookie
    resp = wj({
        "code": 200,
        "message": "登录成功",
        "data": {"username": username, "token": token},
    })
    resp.set_cookie(
        COOKIE_NAME,
        token,
        max_age=_session_hours() * 3600,
        httponly=True,
        samesite="Lax",
        path="/",
    )
    return resp


@routes.view(r"/api/auth/logout")
async def auth_logout(request):
    resp = wj({"code": 200, "message": "已退出"})
    resp.del_cookie(COOKIE_NAME, path="/")
    return resp


@jsondump
@routes.view(r"/api/auth/me")
async def auth_me(request):
    if not auth_enabled():
        return wj({"code": 200, "data": {"enable": False, "username": None}})
    user = resolve_user(request)
    if not user:
        return wj({"code": 401, "message": "未登录"})
    return wj({"code": 200, "data": {"enable": True, "username": user}})


def setup_auth_routes(app):
    app.add_routes(routes)
