"""
查询路由模块
处理单个查询和批量查询相关的路由
"""
import asyncio
import random
import aiohttp
from aiohttp import web
from middlewares import jsondump, wj
from load_config import config
from mlog import logger
from proxy_pool import pool_cache
from utils import is_valid_url


routes = web.RouteTableDef()


@jsondump
@routes.view(r'/query/{path}')
async def geturl(request):
    """单个查询路由"""
    path = request.match_info['path']
    
    # 从app中获取查询处理器
    appth = request.app.get('appth', {})
    bappth = request.app.get('bappth', {})

    if path not in appth and path not in bappth:
        return wj({"code":102,"msg":"不是支持的查询类型"})

    if path not in config.risk_avoidance.allow_type:
        return wj({"code":102,"msg":"不是支持的查询类型"})
    
    if request.method == "GET":
        appname = request.query.get("search")
        pageNum = request.query.get("pageNum")
        pageSize = request.query.get("pageSize")
        proxy = request.query.get("proxy")
        
    if request.method == "POST":
        data = await request.json()
        appname = data.get("search")
        pageNum = data.get("pageNum")
        pageSize = data.get("pageSize")
        proxy = data.get("proxy")

    if not not any(appname.endswith(suffix) for suffix in config.risk_avoidance.prohibit_suffix):
        return wj({"code": 405,"message":"不允许的查询内容"})

    if not appname:
        return wj({"code":101,"msg":"参数错误,请指定search参数"})
    
    if proxy is not None:
        logger.info(f"使用指定代理：{proxy}")
        for i in range(config.captcha.retry_times):
            data = await appth.get(path)(appname, pageNum, pageSize, proxy=f"http://{proxy}")
            if data.get("code", 500) == 200:
                return wj(data)
            if data.get("message", "") == "当前访问已被创宇盾拦截":
                logger.warning("当前访问已被创宇盾拦截")
                return wj(data)
        return wj(data)

    for i in range(config.captcha.retry_times):
        proxy = None
        if config.proxy.local_ipv6_pool.enable:
            proxy = ""

        elif not proxy and config.proxy.tunnel.url:
            if is_valid_url(config.proxy.tunnel.url):
                proxy = config.proxy.tunnel.url
                logger.info(f"使用隧道代理：{proxy}")
            else:
                logger.error(f"当前启用隧道代理，但代理地址无效：{config.proxy.tunnel.url}")
                return wj({"code":500,"message":"当前启用隧道代理，但代理地址无效"})

        elif not proxy and config.proxy.extra_api.url:
            if is_valid_url(config.proxy.extra_api.url):
                if config.proxy.extra_api.auto_maintenace:
                    proxy = await request.app.proxypool.getproxy()
                    logger.info(f"从本地地址池获得代理：{proxy}")
                else:
                    timeout = aiohttp.ClientTimeout(total=config.system.http_client_timeout)
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        async with session.get(config.proxy.extra_api.url) as req:
                            res = await req.text()
                            proxy = f"http://{random.choice(res.split()).strip()}"
                    logger.info(f"从代理提取接口获得代理：{proxy}")
            else:
                logger.error(f"当前启用API提取代理，但API地址无效：{config.proxy.extra_api.url}")
                return wj({"code":500,"message":"当前启用API提取代理，但API地址无效"})
        if path in appth:
            data = await appth.get(path)(appname, pageNum, pageSize, proxy=proxy)
        else:
            data = await bappth.get(path)(appname, proxy=proxy)

        if data.get("code", 500) == 200:
            # 保存历史记录
            db = request.app.get("db")
            if db:
                result_count = len(data.get("params", {}).get("list", [])) if path in appth else len(data.get("params", []))
                db.add_history(path, appname, result_count, data.get("params"))
            return wj(data)
        if data.get("message", "") == "当前访问已被创宇盾拦截":
            logger.warning("当前访问已被创宇盾拦截")
            return wj(data)
    return wj(data)


def setup_query_routes(app):
    """注册查询路由"""
    app.add_routes(routes)

