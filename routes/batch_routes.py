# -*- coding: utf-8 -*-
"""
批量任务路由模块
处理批量查询任务相关的API
"""
import asyncio
import os
import json
import random
from datetime import datetime
import aiohttp
from aiohttp import web
from middlewares import jsondump, wj
from load_config import config
from mlog import logger
from log_collector import log_collector
from proxy_pool import pool_cache
from utils import is_valid_url


routes = web.RouteTableDef()


async def create_task(taskname, data, request, searnum, apptype="web"):
    """创建批量查询任务"""
    # 从app中获取查询处理器
    appth = request.app.get('appth', {})
    bappth = request.app.get('bappth', {})
    
    task = type('Task', (), {
        'curpro': 0,
        'numpro': len(data),
        'domains': [],
        'query_keywords': [],  # 记录每个查询的关键词
        'appname': apptype,
        'cancelled': False
    })()
    
    request.app["tasks"][taskname] = task

    async def process_app(appname, semaphore):
        async with semaphore:
            if task.cancelled:
                return
                
            error_retry_times = 0
            all_results = []  # 将 all_results 移到外层，避免重试时被重置
            
            while error_retry_times < config.captcha.retry_times:
                if task.cancelled:
                    return
                    
                error_retry_times += 1
                proxy = None
                
                try:
                    # 获取代理逻辑
                    if config.proxy.local_ipv6_pool.enable:
                        proxy = ""
                    elif config.proxy.tunnel.url and is_valid_url(config.proxy.tunnel.url):
                        proxy = config.proxy.tunnel.url
                        logger.info(f"使用隧道代理：{proxy}")
                    elif config.proxy.extra_api.url and is_valid_url(config.proxy.extra_api.url):
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

                    # 执行查询 - 支持分页获取所有数据
                    page_num = 1
                    page_size = 26  # 官方单页最大支持26条
                    
                    # 对于违法违规类型，不支持分页
                    if apptype in ["bapp", "bweb", 'bkapp', 'bmapp']:
                        data = await bappth.get(apptype)(appname, proxy=proxy)
                    else:
                        # 循环获取所有页
                        page_retry_count = 0
                        max_page_retry = config.captcha.retry_times  # 单页最大重试次数，统一用配置
                        
                        while True:
                            if task.cancelled:
                                return
                            
                            data = await appth.get(apptype)(appname, pageNum=page_num, pageSize=page_size, proxy=proxy)
                            
                            # 如果请求失败，重试当前页
                            if data["code"] != 200:
                                page_retry_count += 1
                                if page_retry_count >= max_page_retry:
                                    logger.warning(f"批量任务 {taskname} - {appname}: 第{page_num}页重试{max_page_retry}次后仍失败，跳过")
                                    break
                                logger.info(f"批量任务 {taskname} - {appname}: 第{page_num}页查询失败，重试 {page_retry_count}/{max_page_retry}")
                                continue
                            
                            # 重置重试计数
                            page_retry_count = 0
                            
                            current_list = data.get("params", {}).get("list", [])
                            if not current_list:
                                break
                            
                            all_results.extend(current_list)
                            
                            # 检查是否还有更多数据
                            total = data.get("params", {}).get("total", 0)
                            if len(all_results) >= total or len(current_list) < page_size:
                                logger.info(f"批量任务 {taskname} - {appname}: 共获取 {len(all_results)} 条记录（完成）")
                                break
                            
                            page_num += 1
                            logger.info(f"批量任务 {taskname} - {appname}: 已获取 {len(all_results)}/{total} 条记录")
                        
                        # 更新data中的list为所有结果
                        if all_results:
                            if data.get("params"):
                                data["params"]["list"] = all_results
                            else:
                                data = {"code": 200, "params": {"list": all_results, "total": len(all_results)}}

                    # 处理响应
                    if data.get("code") == 500:
                        if "请求验证码时失败" in data.get("message", ''):
                            if proxy and proxy[7:] in pool_cache:
                                del pool_cache[proxy[7:]]
                                logger.info(f"代理无效，已剔除代理：{proxy[7:]}")

                        if data.get("message", "") == "当前访问已被创宇盾拦截":
                            logger.warning(f"当前访问已被创宇盾拦截，批量任务：{taskname}，使用代理：{proxy}")
                        
                        # 如果是验证码失败且已经获取了一些数据，不重试整个查询
                        if all_results:
                            logger.warning(f"批量任务 {taskname} - {appname}: 验证码失败但已获取 {len(all_results)} 条记录，停止继续查询")
                            data = {"code": 200, "params": {"list": all_results, "total": len(all_results)}}
                        else:
                            # 没有获取到任何数据才继续重试
                            continue

                    if data.get("code") == 200:
                        task.curpro += 1
                        # 记录查询关键词
                        task.query_keywords.append(appname)
                        
                        # 处理返回数据
                        result_list = data.get("params", {}).get("list", [])
                        
                        if len(result_list) == 0:
                            if apptype == "web":
                                result_data = [{"contentTypeName": None, "domain": appname, "domainId": None, "leaderName": None,
                                         "limitAccess": None, "mainId": None, "mainLicence": None, "natureName": None,
                                         "serviceId": None, "serviceLicence": None, "unitName": None, "updateRecordTime": None}]
                            elif apptype in ["app", "mapp", "kapp"]:
                                result_data = [{"cityId": None, "countyId": None, "dataId": None, "leaderName": None,
                                         "mainId": None, "mainLicence": None, "mainUnitAddress": None, "mainUnitCertNo": None,
                                         "mainUnitCertType": None, "natureId": None, "natureName": None, "provinceId": None,
                                         "serviceId": None, "serviceLicence": None, "serviceName": appname, "serviceType": None,
                                         "unitName": None, "updateRecordTime": None, "version": None}]
                            else:
                                result_data = [{'blacklistLevel': None, 'serviceName': appname}]
                            task.domains.append(result_data)
                        else:
                            if apptype in ["bapp", "bweb", 'bkapp', 'bmapp']:
                                task.domains.append(data["params"])
                            else:
                                task.domains.append(data["params"]["list"])
                        break
                        
                except Exception as e:
                    logger.error(f"处理任务 {appname} 时发生异常: {e}")
                    
            if error_retry_times >= config.captcha.retry_times:
                logger.warning(f"任务 {appname} 达到最大尝试次数 {config.captcha.retry_times}，仍未成功完成")

    # 使用信号量限制并发数
    semaphore = asyncio.Semaphore(searnum)
    tasks = [process_app(appname, semaphore) for appname in data]
    
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        logger.error(f"批量任务 {taskname} 执行失败: {e}")
    finally:
        # 任务完成后保存结果到文件
        if taskname in request.app["tasks"]:
            task = request.app["tasks"][taskname]
            task.completed = True
            
            # 创建results目录
            results_dir = "batch_results"
            os.makedirs(results_dir, exist_ok=True)
            
            # 保存结果到JSON文件
            result_file = os.path.join(results_dir, f"{taskname}_{int(datetime.now().timestamp())}.json")
            
            try:
                with open(result_file, 'w', encoding='utf-8') as f:
                    result_data = {
                        'task_name': taskname,
                        'task_type': apptype,
                        'total_count': len(data),
                        'completed_count': task.curpro,
                        'query_keywords': task.query_keywords,  # 保存查询关键词列表
                        'result': task.domains
                    }
                    json.dump(result_data, f, ensure_ascii=False, indent=2)
                
                # 更新数据库
                db = request.app.get("db")
                if db:
                    success_count = sum(1 for item in task.domains if item and len(item) > 0)
                    db.update_batch_task(
                        taskname, 
                        completed_count=task.curpro,
                        success_count=success_count,
                        status='completed',
                        result_file=result_file,
                        finish_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    )
                    logger.info(f"批量任务 {taskname} 已完成，结果已保存到 {result_file}")
            except Exception as e:
                logger.error(f"保存任务结果失败: {e}")


@jsondump
@routes.view(r"/query/task")
async def querytask(request):
    """查询任务进度"""
    taskname = request.query.get("taskname")
    task = request.app["tasks"].get(taskname)
    if task is not None:
        return wj({
                "code": 200,
                "curpro": task.curpro,
                "numpro": task.numpro,
                "tasktype": task.appname,
                "progress": int(task.curpro / task.numpro * 100),
                "query_keywords": task.query_keywords,  # 返回查询关键词列表
                "data":task.domains
            })
    else:
        return wj({
            "code":404,
            "message":"任务不存在"
        })


@jsondump
@routes.view(r"/create/task")
async def create_task_catch(request):
    """创建批量查询任务"""
    if request.method == "POST":
        data = await request.json()
        taskname = data.get("task")
        domains = data.get("data")
        seartype = data.get("type","web")

        if seartype not in config.risk_avoidance.allow_type:
            return wj({"code": 405,"message":"不支持的查询类型"})
        
        if len(domains) == 0:
            return wj({"code":400,"message":"提交的查询列表为空"})
        
        domains = [s for s in domains if not any(s.endswith(end) for end in config.risk_avoidance.prohibit_suffix)]

        if len(domains) == 0:
            return wj({"code":400,"message":"在剔除不允许查询的内容后，列表为空，取消任务"})
        
        searnum = int(data.get("searnum", 20))
        
        # 检查是否已存在同名任务
        if taskname in request.app["tasks"]:
            return wj({"code": 409, "message": "任务已存在"})
        
        # 保存任务到数据库
        db = request.app.get("db")
        if db:
            db.add_batch_task(taskname, seartype, len(domains))
        
        # 创建异步任务
        task_coroutine = create_task(taskname, domains, request, searnum, seartype)
        async_task = asyncio.create_task(task_coroutine)
        
        # 添加任务到管理器
        task_manager = request.app.get('task_manager')
        if task_manager:
            task_manager.add_task(taskname, async_task)
        
        logger.info(f"创建批量查询任务：{taskname}")
        log_collector.add_log(f"创建批量查询任务：{taskname}，类型：{seartype}，数量：{len(domains)}")
        return wj({"code": 200,"message":"创建任务成功"})


@jsondump
@routes.view(r"/delete/task")
async def del_task(request):
    """删除批量查询任务"""
    if request.method == "POST":
        data = await request.json()
        taskname = data.get("task")
        
        if taskname in request.app["tasks"]:
            # 标记任务为取消状态
            task = request.app["tasks"][taskname]
            task.cancelled = True
            
            # 从任务管理器中移除
            task_manager = request.app.get('task_manager')
            if task_manager:
                task_manager.remove_task(taskname)
            
            # 从应用任务字典中删除
            del request.app["tasks"][taskname]
            
            logger.warning(f"删除批量查询任务：{taskname}")
            log_collector.add_log(f"删除批量查询任务：{taskname}")
            return wj({"code": 200})
        else:
            return wj({"code":404,"message":"任务不存在，可能已经完成或删除"})


@routes.view(r"/batch/tasks")
async def get_batch_tasks(request):
    """获取批量任务列表"""
    try:
        db = request.app.get("db")
        if not db:
            return {"code": 500, "message": "数据库未初始化"}
        
        limit = int(request.query.get("limit", 20))
        offset = int(request.query.get("offset", 0))
        status = request.query.get("status", "")
        
        tasks = db.get_batch_tasks(limit=limit, offset=offset, status=status if status else None)
        total = db.get_batch_tasks_count(status=status if status else None)
        
        return wj({"code": 200, "data": tasks, "total": total})
    except Exception as e:
        logger.error(f"获取批量任务列表失败: {e}")
        return wj({"code": 500, "message": f"获取任务列表失败: {str(e)}"})


@routes.view(r"/batch/task/{task_name}")
async def get_batch_task_detail(request):
    """获取批量任务详情"""
    try:
        task_name = request.match_info.get("task_name")
        
        db = request.app.get("db")
        if not db:
            return wj({"code": 500, "message": "数据库未初始化"})
        
        task = db.get_batch_task_detail(task_name)
        
        if task:
            # 如果任务已完成且有结果文件，读取结果
            if task.get('result_file') and os.path.exists(task['result_file']):
                try:
                    with open(task['result_file'], 'r', encoding='utf-8') as f:
                        result_data = json.load(f)
                        task['result_data'] = result_data
                except Exception as e:
                    logger.error(f"读取结果文件失败: {e}")
            
            return wj({"code": 200, "data": task})
        else:
            return wj({"code": 404, "message": "任务不存在"})
    except Exception as e:
        logger.error(f"获取批量任务详情失败: {e}")
        return wj({"code": 500, "message": f"获取任务详情失败: {str(e)}"})


@routes.view(r"/batch/task/delete/{task_name}")
async def delete_batch_task_api(request):
    """删除批量任务"""
    try:
        task_name = request.match_info.get("task_name")
        
        db = request.app.get("db")
        if not db:
            return wj({"code": 500, "message": "数据库未初始化"})
        
        success = db.delete_batch_task(task_name)
        
        if success:
            return wj({"code": 200, "message": "删除成功"})
        else:
            return wj({"code": 500, "message": "删除失败"})
    except Exception as e:
        logger.error(f"删除批量任务失败: {e}")
        return wj({"code": 500, "message": f"删除任务失败: {str(e)}"})


def setup_batch_routes(app):
    """注册批量任务路由"""
    app.add_routes(routes)

