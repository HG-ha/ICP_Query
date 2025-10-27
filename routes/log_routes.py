# -*- coding: utf-8 -*-
"""
日志管理路由模块
处理系统日志相关的API
"""
from aiohttp import web
from middlewares import jsondump, wj
from mlog import logger
from log_collector import log_collector


routes = web.RouteTableDef()


@jsondump
@routes.view(r"/logs/realtime")
async def get_realtime_logs(request):
    """获取实时日志"""
    limit = int(request.query.get('limit', 500))
    
    try:
        logs = log_collector.get_logs(limit)
        return wj({"code": 200, "data": logs, "total": len(logs)})
    except Exception as e:
        logger.error(f"获取实时日志失败: {e}")
        return wj({"code": 500, "message": f"获取实时日志失败: {str(e)}"})


@jsondump
@routes.view(r"/logs/clear")
async def clear_logs(request):
    """清空实时日志"""
    try:
        log_collector.clear()
        return wj({"code": 200, "message": "日志已清空"})
    except Exception as e:
        return wj({"code": 500, "message": f"清空日志失败: {str(e)}"})


def setup_log_routes(app):
    """注册日志管理路由"""
    app.add_routes(routes)

