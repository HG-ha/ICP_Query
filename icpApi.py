'''
author     : Yiming
Creat time : 2023/9/9 21:03
Blog       : https://www.cnblogs.com/ymer
Github     : https://github.com/HG-ha
Home       : https://api.wer.plus
QQ group   : 376957298,1029212047
'''

import aiohttp
from functools import wraps
from aiohttp import web
import json
from ymicp import beian

# 跨域参数
corscode = {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, POST, OPTIONS', # 需要限制请求就在这里增删
                'Access-Control-Allow-Headers': '*',
                'Server':'Welcome to api.wer.plus',
            }

# 实例化路由
routes = web.RouteTableDef()

# 异步json序列化
def jsondump(func):
    @wraps(func)
    async def wrapper(*args,**kwargs):
        result = await func(*args,**kwargs)
        try:
            return json.dumps(result ,ensure_ascii=False)
        except:
            return result
    return wrapper

# 封装一下web.json_resp
wj = lambda *args,**kwargs: web.json_response(*args,**kwargs)

# 处理OPTIONS和跨域的中间件
@jsondump
async def options_middleware(app, handler):
    async def middleware(request):
        # 处理 OPTIONS 请求，直接返回空数据和允许跨域的 header
        if request.method == 'OPTIONS':
            return wj(headers=corscode)
        
        # 继续处理其他请求,同时处理异常响应，返回正常json值或自定义页面
        try:
            response = await handler(request)
            response.headers.update(corscode)
            if response.status == 200:
                return response
        except web.HTTPException as ex:
            if ex.status == 404:
                return wj({'code': ex.status,"msg":"查询请访问http://0.0.0.0:16181/query/{name}"},headers=corscode)
            return wj({'code': ex.status,"msg":ex.reason},headers=corscode)
        
        return response
    return middleware

@jsondump
@routes.view(r'/query/{path}')
async def geturl(request):
    path = request.match_info['path']

    if path not in appth and path not in bappth:
        return wj({"code":102,"msg":"不是支持的查询类型"})
    
    if request.method == "GET":
        appname = request.query.get("search")
        pageNum = request.query.get("pageNum")
        pageSize = request.query.get("pageSize")
    if request.method == "POST":
        data = await request.json()
        appname = data.get("search")
        pageNum = data.get("pageNum")
        pageSize = data.get("pageSize")

    if not appname:
        return wj({"code":101,"msg":"参数错误,请指定search参数"})
    
    if path in appth:
        return wj(await appth.get(path)(
            appname,
            pageNum if str(pageNum) else '',
            pageSize if str(pageSize) else ''
            ))
    else:
        return wj(await bappth.get(path)(appname))

if __name__ == '__main__':

    myicp = beian()
    appth = {
        "web": myicp.ymWeb,    # 网站
        "app": myicp.ymApp,    # APP
        "mapp": myicp.ymMiniApp,   # 小程序
        "kapp": myicp.ymKuaiApp,    # 快应用
    }
    
    # 违法违规应用不支持翻页
    bappth = {
        "bweb": myicp.bymWeb,    # 违法违规网站
        "bapp": myicp.bymApp,    # 违法违规APP
        "bmapp": myicp.bymMiniApp,   # 违法违规小程序
        "bkapp": myicp.bymKuaiApp    # 违法违规快应用
    }
    app = web.Application()
    app.add_routes(routes)

    app.middlewares.append(options_middleware)
    web.run_app(
        app,
        host = "0.0.0.0",
        port = 16181
    )
