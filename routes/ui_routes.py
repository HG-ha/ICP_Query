# -*- coding: utf-8 -*-
"""
UI路由模块
处理Web UI相关的路由
"""
from aiohttp import web
import aiohttp_jinja2
from load_config import config


routes = web.RouteTableDef()


if config.system.web_ui:
    @routes.view(r"/")
    async def index(request):
        """Web UI 首页"""
        response = aiohttp_jinja2.render_template("index.html", request, {})
        return response


def setup_ui_routes(app):
    """注册UI路由"""
    app.add_routes(routes)

