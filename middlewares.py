"""
中间件模块
包含各种请求处理中间件
"""
from functools import wraps
import json
from aiohttp import web
from mlog import logger
from load_config import config


# 跨域参数
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "*",
    "Server": "are you ok?",
}


def jsondump(func):
    """异步json序列化装饰器"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        result = await func(*args, **kwargs)
        try:
            # 返回 web.Response 对象而不是纯字符串
            json_text = json.dumps(result, ensure_ascii=False)
            return web.Response(
                text=json_text,
                content_type='application/json',
                charset='utf-8'
            )
        except Exception as e:
            logger.error(f"JSON序列化失败: {e}, result: {result}")
            # 如果序列化失败，尝试返回错误信息
            return web.Response(
                text=json.dumps({"code": 500, "message": f"JSON序列化失败: {str(e)}"}, ensure_ascii=False),
                content_type='application/json',
                charset='utf-8'
            )
    return wrapper


# 封装一下web.json_response
wj = lambda *args, **kwargs: web.json_response(*args, **kwargs)


async def options_middleware(app, handler):
    """处理OPTIONS和跨域的中间件"""
    async def middleware(request):
        # 处理 OPTIONS 请求，直接返回空数据和允许跨域的 header
        if request.method == "OPTIONS":
            return wj(headers=CORS_HEADERS)

        # 继续处理其他请求,同时处理异常响应，返回正常json值或自定义页面
        try:
            response = await handler(request)
            # 确保response是Response对象再更新headers
            if hasattr(response, 'headers'):
                response.headers.update(CORS_HEADERS)
                return response
            elif not hasattr(response, 'status'):
                # 如果返回的不是Response对象，包装成Response
                return web.Response(text=str(response), headers=CORS_HEADERS)
            else:
                return response
        except web.HTTPException as ex:
            if ex.status == 404:
                return wj(
                    {
                        "code": ex.status,
                        "msg": f"查询请访问http://{config.system.host}:{config.system.port}",
                    },
                    headers=CORS_HEADERS,
                )
            return wj({"code": ex.status, "msg": ex.reason}, headers=CORS_HEADERS)
        except Exception as e:
            logger.error(f"中间件处理请求时出错: {e}")
            return wj({"code": 500, "msg": str(e)}, headers=CORS_HEADERS)

    return middleware

