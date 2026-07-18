# -*- coding: utf-8 -*-
"""
中间件模块
包含各种请求处理中间件
"""
from functools import wraps
import json
from aiohttp import web
from mlog import logger
from load_config import config
from auth import auth_enabled, is_public_path, resolve_user


# 跨域参数
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "*",
    "Server": "are you ok?",
}


def _safe_json_dumps(obj):
    """安全的 JSON 序列化函数，Bug 4 修复"""
    try:
        return json.dumps(obj, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        try:
            if isinstance(obj, dict):
                return json.dumps({str(k): str(v) for k, v in obj.items()}, ensure_ascii=False)
            else:
                return json.dumps({"error": "无法序列化数据", "type": str(type(obj))}, ensure_ascii=False)
        except Exception:
            return '{"code": 500, "message": "JSON 序列化失败"}'


def jsondump(func):
    """异步 json 序列化装饰器"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        result = await func(*args, **kwargs)
        try:
            json_text = _safe_json_dumps(result)
            return web.Response(
                text=json_text,
                content_type='application/json',
                charset='utf-8'
            )
        except Exception as e:
            logger.error(f"JSON 响应生成失败：{e}")
            return web.Response(
                text='{"code": 500, "message": "内部服务器错误"}',
                content_type='application/json',
                charset='utf-8',
                status=500
            )
    return wrapper


# 封装一下 web.json_response
wj = lambda *args, **kwargs: web.json_response(*args, **kwargs)


@web.middleware
async def auth_middleware(request, handler):
    """账号鉴权中间件"""
    if request.method == "OPTIONS":
        return await handler(request)
    if not auth_enabled():
        return await handler(request)
    path = request.path
    if is_public_path(path, request.method):
        return await handler(request)
    user = resolve_user(request)
    if not user:
        # HTML 首页返回 401 JSON，前端展示登录页
        return wj(
            {"code": 401, "message": "未登录或会话已过期"},
            status=401,
            headers=CORS_HEADERS,
        )
    request["user"] = user
    return await handler(request)


@web.middleware
async def options_middleware(request, handler):
    """处理 OPTIONS 和跨域的中间件"""
    if request.method == "OPTIONS":
        return wj(headers=CORS_HEADERS)

    try:
        response = await handler(request)
        if hasattr(response, "headers"):
            response.headers.update(CORS_HEADERS)
            return response
        elif not hasattr(response, "status"):
            return web.Response(text=str(response), headers=CORS_HEADERS)
        else:
            return response
    except web.HTTPException as ex:
        if ex.status == 404:
            return wj(
                {
                    "code": ex.status,
                    "msg": f"查询请访问 http://{config.system.host}:{config.system.port}",
                },
                headers=CORS_HEADERS,
            )
        return wj({"code": ex.status, "msg": ex.reason}, headers=CORS_HEADERS)
    except Exception as e:
        logger.error(f"中间件处理请求时出错：{e}")
        return wj({"code": 500, "msg": str(e)}, headers=CORS_HEADERS)
