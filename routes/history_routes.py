# -*- coding: utf-8 -*-
"""
历史记录路由模块
处理查询历史记录相关的API
"""
from aiohttp import web
from middlewares import jsondump, wj


routes = web.RouteTableDef()


@jsondump
@routes.view(r"/history")
async def get_history(request):
    """获取历史记录列表"""
    limit = int(request.query.get("limit", 50))
    offset = int(request.query.get("offset", 0))
    search_type = request.query.get("type")
    
    db = request.app.get("db")
    if not db:
        return wj({"code": 500, "message": "数据库未初始化"})
    
    history_list = db.get_history(limit=limit, offset=offset, search_type=search_type)
    total_count = db.get_history_count(search_type=search_type)
    
    return wj({
        "code": 200,
        "data": history_list,
        "total": total_count,
        "limit": limit,
        "offset": offset
    })


@jsondump
@routes.view(r"/history/{history_id:\d+}")
async def get_history_detail(request):
    """获取历史记录详情"""
    history_id = int(request.match_info['history_id'])
    
    db = request.app.get("db")
    if not db:
        return wj({"code": 500, "message": "数据库未初始化"})
    
    history_detail = db.get_history_detail(history_id)
    
    if history_detail:
        return wj({"code": 200, "data": history_detail})
    else:
        return wj({"code": 404, "message": "历史记录不存在"})


@jsondump
@routes.view(r"/history/delete/{history_id:\d+}")
async def delete_history(request):
    """删除历史记录"""
    history_id = int(request.match_info['history_id'])
    
    db = request.app.get("db")
    if not db:
        return wj({"code": 500, "message": "数据库未初始化"})
    
    success = db.delete_history(history_id)
    
    if success:
        return wj({"code": 200, "message": "删除成功"})
    else:
        return wj({"code": 500, "message": "删除失败"})


@jsondump
@routes.view(r"/history/clear")
async def clear_history(request):
    """清空历史记录"""
    if request.method == "POST":
        data = await request.json()
        search_type = data.get("type")
        
        db = request.app.get("db")
        if not db:
            return wj({"code": 500, "message": "数据库未初始化"})
        
        success = db.clear_history(search_type=search_type)
        
        if success:
            return wj({"code": 200, "message": "清空成功"})
        else:
            return wj({"code": 500, "message": "清空失败"})


def setup_history_routes(app):
    """注册历史记录路由"""
    app.add_routes(routes)

