from functools import wraps
from aiohttp import web
import json
from ymicp import beian
import random
from datetime import datetime
import json
import asyncio
import aiohttp
import aiohttp_jinja2
import jinja2
import re
import sys
import os
import signal
from cachetools import TTLCache
from mlog import logger
from load_config import config
import subprocess
import uuid
import locale
import weakref
from database import Database
from collections import deque
import threading
import logging

VERSION="0.6.2"

pool_cache = TTLCache(maxsize=config.proxy.extra_api.pool_num, 
                      ttl=config.proxy.extra_api.timeout - config.proxy.extra_api.timeout_drop)

# 实时日志收集器
class LogCollector:
    def __init__(self, maxlen=1000):
        self.logs = deque(maxlen=maxlen)
        self.lock = threading.Lock()
    
    def add_log(self, message, level='INFO'):
        with self.lock:
            self.logs.append({
                'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'message': message,
                'level': level
            })
    
    def get_logs(self, limit=500):
        with self.lock:
            logs_list = list(self.logs)
            return logs_list[-limit:] if len(logs_list) > limit else logs_list
    
    def clear(self):
        with self.lock:
            self.logs.clear()

# 自定义日志处理器，将日志添加到LogCollector
class CollectorHandler(logging.Handler):
    def __init__(self, collector):
        super().__init__()
        self.collector = collector
    
    def emit(self, record):
        try:
            msg = self.format(record)
            # 过滤掉aiohttp.access的日志，因为太多了
            if 'aiohttp.access' not in record.name:
                self.collector.add_log(msg, record.levelname)
        except Exception:
            self.handleError(record)

log_collector = LogCollector()

# 全局任务管理器
class TaskManager:
    def __init__(self):
        self._tasks = weakref.WeakValueDictionary()
        self._semaphores = {}
        
    def add_task(self, task_name, task):
        self._tasks[task_name] = task
        
    def get_task(self, task_name):
        return self._tasks.get(task_name)
        
    def remove_task(self, task_name):
        if task_name in self._tasks:
            task = self._tasks[task_name]
            if not task.done():
                task.cancel()
            del self._tasks[task_name]
            
    def get_semaphore(self, name, limit):
        if name not in self._semaphores:
            self._semaphores[name] = asyncio.Semaphore(limit)
        return self._semaphores[name]

task_manager = TaskManager()

def signal_handler(sig, frame):
    if sig == signal.SIGINT:
        logger.warning('收到关闭信号，程序停止')
        # 清理所有任务
        for task_name in list(task_manager._tasks.keys()):
            task_manager.remove_task(task_name)
        sys.exit()

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def is_valid_url(url):
    regex = re.compile(
        r'^(?:http)s?://'  # http:// or https:// or ftp://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|'  # ...or ipv4
        r'\[?[A-F0-9]*:[A-F0-9:]+\]?)'  # ...or ipv6
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return re.match(regex, url) is not None

def get_resource_path(relative_path):
    """获取打包后的可执行文件中的资源文件路径"""
    if getattr(sys, 'frozen', False):  # 如果是打包后的程序
        app_path = os.path.dirname(sys.executable)
    else:
        app_path = os.path.dirname(os.path.abspath(__file__))

    return os.path.join(app_path, relative_path)

# 检查IPv6地址是否为公网IP
def is_public_ipv6(ipv6):
    return not (ipv6.startswith("fe80") or ipv6.startswith("fc00") or ipv6.startswith("fd00"))

def _run_cmd_capture(cmd):
    """执行系统命令并自动多编码尝试解码"""
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate(timeout=5)
    except Exception:
        return ""
    if not out:
        return ""
    enc_candidates = [
        "utf-8",
        locale.getpreferredencoding(False) or "",
        "gbk",
        "cp936",
        "latin-1",
    ]
    for enc in enc_candidates:
        if not enc:
            continue
        try:
            return out.decode(enc)
        except Exception:
            continue
    return out.decode("utf-8", errors="ignore")

# 获取本地IPv6地址
def get_local_ipv6_addresses():
    addresses = []
    try:
        if os.name == 'nt':
            output = _run_cmd_capture(["netsh", "interface", "ipv6", "show", "addresses"])
            if not output:
                return []
            for line in output.splitlines():
                line_strip = line.strip()
                if any(k in line_strip for k in ("公用", "手动", "Public", "Manual")) and ":" in line_strip:
                    parts = line_strip.split()
                    candidate = parts[-1].split("/")[0]
                    if ":" in candidate and is_public_ipv6(candidate):
                        addresses.append(candidate)
        else:
            output = _run_cmd_capture(["ip", "-6", "addr", "show"])
            if not output:
                return []
            for line in output.splitlines():
                line_strip = line_strip = line.strip()
                if ("inet6" in line_strip) and ("scope global" in line_strip):
                    try:
                        candidate = line_strip.split()[1].split("/")[0]
                        if is_public_ipv6(candidate):
                            addresses.append(candidate)
                    except:
                        continue
    except Exception:
        return []
    return list(dict.fromkeys(addresses))

# 配置指定数量的IPv6地址
def configure_ipv6_addresses(prefix, count, adapter_name):
    if os.name == 'nt':  # Windows
        for _ in range(count):
            guid = uuid.uuid4().hex
            new_temp_ipv6 = f"{prefix}:{guid[:4]}:{guid[4:8]}:{guid[8:12]}:{guid[12:16]}"
            subprocess.run([
                "netsh", "interface", "ipv6", "add", "address", adapter_name, new_temp_ipv6,
                "store=active", "skipassource=true"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:  # Linux
        for _ in range(count):
            guid = uuid.uuid4().hex
            new_temp_ipv6 = f"{prefix}:{guid[:4]}:{guid[4:8]}:{guid[8:12]}:{guid[12:16]}"
            subprocess.run([
                "ip", "-6", "addr", "add", new_temp_ipv6, "dev", adapter_name
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# 初始化IPv6地址池
async def init_ipv6_pool(app):
    logger.info("启用本地IPv6轮询")
    local_ipv6_addresses = get_local_ipv6_addresses()
    public_ipv6_addresses = [addr for addr in local_ipv6_addresses if is_public_ipv6(addr)]
    if len(public_ipv6_addresses) < config.proxy.local_ipv6_pool.pool_num:
        prefix = ":".join(public_ipv6_addresses[0].split(":")[0:4])  # 获取前四位作为前缀
        configure_ipv6_addresses(prefix, config.proxy.local_ipv6_pool.pool_num - len(public_ipv6_addresses), config.proxy.local_ipv6_pool.ipv6_network_card)
        logger.info(f"已配置 {config.proxy.local_ipv6_pool.pool_num - len(public_ipv6_addresses)} 个新的IPv6地址")
    else:
        logger.info("已有足够的IPv6地址，无需配置")
    asyncio.create_task(check_and_update_ipv6_pool())

async def check_and_update_ipv6_pool():
    while True:
        local_ipv6_addresses = get_local_ipv6_addresses()

        public_ipv6_addresses = [addr for addr in local_ipv6_addresses if is_public_ipv6(addr)]
        if len(public_ipv6_addresses) < config.proxy.local_ipv6_pool.pool_num:
            prefix = ":".join(public_ipv6_addresses[0].split(":")[0:4])  # 获取前四位作为前缀
            configure_ipv6_addresses(prefix, config.proxy.local_ipv6_pool.pool_num - len(public_ipv6_addresses), config.proxy.local_ipv6_pool.ipv6_network_card)
            logger.info(f"已补充 {config.proxy.local_ipv6_pool.pool_num - len(public_ipv6_addresses)} 个新的IPv6地址")
        await asyncio.sleep(config.proxy.local_ipv6_pool.check_interval)

# 跨域参数
corscode = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",  # 需要限制请求就在这里增删
    "Access-Control-Allow-Headers": "*",
    "Server": "are you ok?",
}

# 实例化路由
routes = web.RouteTableDef()


class Pool:
    def __init__(self) -> None:
        # 获取代理地址的接口
        self.proxy_url = config.proxy.extra_api.url
        # 代理剩余多少秒时丢弃
        self.discard = config.proxy.extra_api.timeouut_drop
        # 多少秒获取一次代理，当前接口限制提取频率为1s，适当调整
        self.period = config.proxy.extra_api.extra_interval
        # 代理地址池同时存在多少代理
        self.number = config.proxy.extra_api.pool_num
        # 代理池的统一session
        self.session = None
        # 更新锁，防止并发更新
        self._update_lock = asyncio.Lock()
        # 启动定时任务，维护地址池
        self._update_task = None
        
    async def start(self):
        """启动代理池维护任务"""
        if self._update_task is None:
            self._update_task = asyncio.create_task(self.cron_update())

    async def stop(self):
        """停止代理池维护任务"""
        if self._update_task:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass
        await self._close_session()

    async def cron_create(self):
        await self.start()

    async def _init_session(self):
        if self.session is None:
            timeout = aiohttp.ClientTimeout(total=config.system.http_client_timeout)
            self.session = aiohttp.ClientSession(timeout=timeout)

    async def _close_session(self):
        if self.session is not None:
            await self.session.close()
            self.session = None

    # 获取新的代理到代理地址池
    async def _update(self):
        async with self._update_lock:
            if len(pool_cache) >= self.number:
                logger.info(f"代理池饱满，无需更新代理，当前池内数量：{len(pool_cache)}")
                return
                
            try:
                await self._init_session()
                async with self.session.get(self.proxy_url) as req:
                    res = await req.text()
                    proxy_list = [p.strip() for p in res.split("\n") if p.strip()]
                    
                    if len(proxy_list) == 0:
                        logger.error("提取到的IP为0")
                        return
                        
                    endtime = datetime.now().timestamp()
                    
                    if config.proxy.extra_api.check_proxy:
                        await self._check_and_add_proxies(proxy_list, endtime)
                    else:
                        for address in proxy_list:
                            if len(pool_cache) >= self.number:
                                break
                            pool_cache[address] = endtime
                            
                    logger.info(f"更新代理池成功，当前代理数量：{len(pool_cache)}")
                    
            except Exception as e:
                logger.error(f"更新代理池失败: {e}")

    async def _check_and_add_proxies(self, proxy_list, endtime):
        """并发检查代理可用性并添加到池中"""
        semaphore = asyncio.Semaphore(config.proxy.extra_api.check_proxy_num)
        
        async def check_proxy(address):
            async with semaphore:
                if len(pool_cache) >= self.number:
                    return
                    
                timeout = aiohttp.ClientTimeout(total=config.proxy.extra_api.proxy_timeout)
                try:
                    from aiohttp import TCPConnector
                    async with aiohttp.ClientSession(
                        timeout=timeout, connector=TCPConnector(ssl=False)
                    ) as session:
                        async with session.get(
                            "http://ifconfig.me/ip", proxy=f"http://{address}"
                        ) as req:
                            await req.text()
                    
                    if len(pool_cache) < self.number:
                        pool_cache[address] = endtime
                        logger.info(f"入库代理成功：{address}")
                except Exception:
                    logger.info(f"入库检测代理不可用：{address}")

        # 使用asyncio.gather处理并发任务，添加异常处理
        tasks = [check_proxy(address) for address in proxy_list]
        await asyncio.gather(*tasks, return_exceptions=True)

    # 定时任务,更新地址池
    async def cron_update(self):
        try:
            while True:
                await self._update()
                await asyncio.sleep(self.period)
        except asyncio.CancelledError:
            logger.info("代理池更新任务已取消")
            raise

    async def getproxy(self, num=1):
        # 等待代理池有可用代理
        timeout = 30  # 30秒超时
        start_time = asyncio.get_event_loop().time()
        
        while True:
            if len(pool_cache) != 0:
                break
            if asyncio.get_event_loop().time() - start_time > timeout:
                raise TimeoutError("等待代理超时")
            await asyncio.sleep(0.1)
            
        random_key = f"http://{random.choice(list(pool_cache.keys()))}"
        return random_key

# 异步json序列化
def jsondump(func):
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


# 封装一下web.json_resp
wj = lambda *args, **kwargs: web.json_response(*args, **kwargs)


# 处理OPTIONS和跨域的中间件
async def options_middleware(app, handler):
    async def middleware(request):
        # 处理 OPTIONS 请求，直接返回空数据和允许跨域的 header
        if request.method == "OPTIONS":
            return wj(headers=corscode)

        # 继续处理其他请求,同时处理异常响应，返回正常json值或自定义页面
        try:
            response = await handler(request)
            # 确保response是Response对象再更新headers
            if hasattr(response, 'headers'):
                response.headers.update(corscode)
                return response
            elif not hasattr(response, 'status'):
                # 如果返回的不是Response对象，包装成Response
                return web.Response(text=str(response), headers=corscode)
            else:
                return response
        except web.HTTPException as ex:
            if ex.status == 404:
                return wj(
                    {
                        "code": ex.status,
                        "msg": f"查询请访问http://{config.system.host}:{config.system.port}",
                    },
                    headers=corscode,
                )
            return wj({"code": ex.status, "msg": ex.reason}, headers=corscode)
        except Exception as e:
            logger.error(f"中间件处理请求时出错: {e}")
            return wj({"code": 500, "msg": str(e)}, headers=corscode)

    return middleware


# 创建任务队列
async def create_task(taskname, data, request, searnum, apptype="web"):
    task = type('Task', (), {
        'curpro': 0,
        'numpro': len(data),
        'domains': [],
        'appname': apptype,
        'cancelled': False
    })()
    
    request.app["tasks"][taskname] = task

    async def process_app(appname, semaphore):
        async with semaphore:
            if task.cancelled:
                return
                
            error_retry_times = 0
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

                    # 执行查询
                    data = await appth.get(apptype)(appname, proxy=proxy)

                    # 处理响应
                    if data["code"] == 500:
                        if "请求验证码时失败" in data.get("message", ''):
                            if proxy and proxy[7:] in pool_cache:
                                del pool_cache[proxy[7:]]
                                logger.info(f"代理无效，已剔除代理：{proxy[7:]}")

                        if data.get("message", "") == "当前访问已被创宇盾拦截":
                            logger.warning(f"当前访问已被创宇盾拦截，批量任务：{taskname}，使用代理：{proxy}")

                    if data["code"] == 200:
                        task.curpro += 1
                        # 处理返回数据
                        if len(data["params"]["list"]) == 0:
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
            import os
            results_dir = "batch_results"
            os.makedirs(results_dir, exist_ok=True)
            
            # 保存结果到JSON文件
            from datetime import datetime
            result_file = os.path.join(results_dir, f"{taskname}_{int(datetime.now().timestamp())}.json")
            
            try:
                import json
                with open(result_file, 'w', encoding='utf-8') as f:
                    result_data = {
                        'task_name': taskname,
                        'task_type': apptype,
                        'total_count': len(data),
                        'completed_count': task.curpro,
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

# 查询任务进度
@jsondump
@routes.view(r"/query/task")
async def querytask(request):
    taskname = request.query.get("taskname")
    task = request.app["tasks"].get(taskname)
    if task is not None:
        return wj({
                "code": 200,
                "curpro": task.curpro,
                "numpro": task.numpro,
                "tasktype": task.appname,
                "progress": int(task.curpro / task.numpro * 100),
                "data":task.domains
            })
    else:
        return wj({
            "code":404,
            "message":"任务不存在"
        })


# 创建批量查询任务
@jsondump
@routes.view(r"/create/task")
async def create_task_catch(request):
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
        task_manager.add_task(taskname, async_task)
        
        logger.info(f"创建批量查询任务：{taskname}")
        log_collector.add_log(f"创建批量查询任务：{taskname}，类型：{seartype}，数量：{len(domains)}")
        return wj({"code": 200,"message":"创建任务成功"})

# 删除批量查询任务
@jsondump
@routes.view(r"/delete/task")
async def del_task(request):
    if request.method == "POST":
        data = await request.json()
        taskname = data.get("task")
        
        if taskname in request.app["tasks"]:
            # 标记任务为取消状态
            task = request.app["tasks"][taskname]
            task.cancelled = True
            
            # 从任务管理器中移除
            task_manager.remove_task(taskname)
            
            # 从应用任务字典中删除
            del request.app["tasks"][taskname]
            
            logger.warning(f"删除批量查询任务：{taskname}")
            log_collector.add_log(f"删除批量查询任务：{taskname}")
            return wj({"code": 200})
        else:
            return wj({"code":404,"message":"任务不存在，可能已经完成或删除"})

@jsondump
@routes.view(r'/query/{path}')
async def geturl(request):
    path = request.match_info['path']

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

# 历史记录相关路由
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

# 批量任务管理相关路由
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
                    import json
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

# 配置管理相关路由
@jsondump
@routes.view(r"/config")
async def get_config(request):
    """获取配置信息"""
    try:
        config_data = {
            "system": {
                "host": config.system.host,
                "port": config.system.port,
                "http_client_timeout": config.system.http_client_timeout,
                "web_ui": config.system.web_ui,
                "detail_concurrency": config.system.detail_concurrency
            },
            "captcha": {
                "enable": config.captcha.enable,
                "save_failed_img": config.captcha.save_failed_img,
                "save_failed_img_path": config.captcha.save_failed_img_path,
                "device": config.captcha.device,
                "retry_times": config.captcha.retry_times,
                "coding_code": config.captcha.coding_code,
                "coding_show": config.captcha.coding_show
            },
            "proxy": {
                "local_ipv6_pool": {
                    "enable": config.proxy.local_ipv6_pool.enable,
                    "pool_num": config.proxy.local_ipv6_pool.pool_num,
                    "check_interval": config.proxy.local_ipv6_pool.check_interval,
                    "ipv6_network_card": config.proxy.local_ipv6_pool.ipv6_network_card
                },
                "tunnel": {
                    "url": config.proxy.tunnel.url or ""
                },
                "extra_api": {
                    "url": config.proxy.extra_api.url or "",
                    "extra_interval": config.proxy.extra_api.extra_interval,
                    "timeout": config.proxy.extra_api.timeout,
                    "timeout_drop": config.proxy.extra_api.timeout_drop,
                    "check_proxy": config.proxy.extra_api.check_proxy,
                    "proxy_timeout": config.proxy.extra_api.proxy_timeout,
                    "check_proxy_num": config.proxy.extra_api.check_proxy_num,
                    "auto_maintenace": config.proxy.extra_api.auto_maintenace,
                    "pool_num": config.proxy.extra_api.pool_num
                }
            },
            "log": {
                "dir": config.log.dir,
                "file_head": config.log.file_head,
                "backup_count": config.log.backup_count,
                "save_log": config.log.save_log,
                "output_console": config.log.output_console
            }
        }
        return wj({"code": 200, "data": config_data})
    except Exception as e:
        logger.error(f"读取配置失败: {e}")
        return wj({"code": 500, "message": f"读取配置失败: {str(e)}"})

@jsondump
@routes.view(r"/config/save")
async def save_config(request):
    """保存配置"""
    if request.method == "POST":
        try:
            import yaml
            data = await request.json()
            
            # 构建配置字典
            config_dict = {
                "system": {
                    "host": data.get("system", {}).get("host", "0.0.0.0"),
                    "port": int(data.get("system", {}).get("port", 16181)),
                    "http_client_timeout": int(data.get("system", {}).get("http_client_timeout", 5)),
                    "web_ui": bool(data.get("system", {}).get("web_ui", True)),
                    "detail_concurrency": int(data.get("system", {}).get("detail_concurrency", 5))
                },
                "captcha": {
                    "enable": bool(data.get("captcha", {}).get("enable", True)),
                    "save_failed_img": bool(data.get("captcha", {}).get("save_failed_img", False)),
                    "save_failed_img_path": data.get("captcha", {}).get("save_failed_img_path", "faile_captcha"),
                    "device": data.get("captcha", {}).get("device", ["CPU"]),
                    "retry_times": int(data.get("captcha", {}).get("retry_times", 2)),
                    "coding_code": data.get("captcha", {}).get("coding_code", "auto"),
                    "coding_show": bool(data.get("captcha", {}).get("coding_show", False))
                },
                "proxy": {
                    "local_ipv6_pool": {
                        "enable": bool(data.get("proxy", {}).get("local_ipv6_pool", {}).get("enable", False)),
                        "pool_num": int(data.get("proxy", {}).get("local_ipv6_pool", {}).get("pool_num", 88)),
                        "check_interval": int(data.get("proxy", {}).get("local_ipv6_pool", {}).get("check_interval", 1)),
                        "ipv6_network_card": data.get("proxy", {}).get("local_ipv6_pool", {}).get("ipv6_network_card", "eth0")
                    },
                    "tunnel": {
                        "url": data.get("proxy", {}).get("tunnel", {}).get("url") or None
                    },
                    "extra_api": {
                        "url": data.get("proxy", {}).get("extra_api", {}).get("url") or None,
                        "extra_interval": int(data.get("proxy", {}).get("extra_api", {}).get("extra_interval", 3)),
                        "timeout": int(data.get("proxy", {}).get("extra_api", {}).get("timeout", 100)),
                        "timeout_drop": int(data.get("proxy", {}).get("extra_api", {}).get("timeout_drop", 8)),
                        "check_proxy": bool(data.get("proxy", {}).get("extra_api", {}).get("check_proxy", True)),
                        "proxy_timeout": float(data.get("proxy", {}).get("extra_api", {}).get("proxy_timeout", 0.5)),
                        "check_proxy_num": int(data.get("proxy", {}).get("extra_api", {}).get("check_proxy_num", 20)),
                        "auto_maintenace": bool(data.get("proxy", {}).get("extra_api", {}).get("auto_maintenace", True)),
                        "pool_num": int(data.get("proxy", {}).get("extra_api", {}).get("pool_num", 100))
                    }
                },
                "risk_avoidance": {
                    "allow_type": ["web", "app", "mapp", "kapp", "bweb", "bapp", "bmapp", "bkapp"],
                    "prohibit_suffix": []
                },
                "log": {
                    "dir": data.get("log", {}).get("dir", "logs"),
                    "file_head": data.get("log", {}).get("file_head", "ymicp"),
                    "backup_count": int(data.get("log", {}).get("backup_count", 7)),
                    "save_log": bool(data.get("log", {}).get("save_log", False)),
                    "output_console": bool(data.get("log", {}).get("output_console", True))
                }
            }
            
            # 备份原配置文件
            config_path = get_resource_path("config.yml")
            backup_path = get_resource_path("config.yml.backup")
            
            import shutil
            if os.path.exists(config_path):
                shutil.copy(config_path, backup_path)
            
            # 保存新配置
            with open(config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config_dict, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            
            logger.info("配置文件已更新，需要重启服务生效")
            log_collector.add_log("配置文件已更新，需要重启服务生效")
            return wj({"code": 200, "message": "配置保存成功，重启服务后生效"})
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")
            return wj({"code": 500, "message": f"保存配置失败: {str(e)}"})

# 日志管理相关路由
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

if config.system.web_ui:
    @routes.view(r"/")
    async def index(request):
        response = aiohttp_jinja2.render_template("index.html", request, {})
        return response

async def init_proxy_pool(app):
    if not hasattr(app, "proxypool"):
        app.proxypool = Pool()
        await app.proxypool.start()
        logger.info("初始化地址池维护任务")

async def cleanup_proxy_pool(app):
    if hasattr(app, "proxypool"):
        await app.proxypool.stop()
        logger.info("清理地址池维护任务")

if __name__ == "__main__":

    myicp = beian()
    appth = {
        "web": myicp.ymWeb,  # 网站
        "app": myicp.ymApp,  # APP
        "mapp": myicp.ymMiniApp,  # 小程序
        "kapp": myicp.ymKuaiApp,  # 快应用
    }

    # 违法违规应用不支持翻页
    bappth = {
        "bweb": myicp.bymWeb,  # 违法违规网站
        "bapp": myicp.bymApp,  # 违法违规APP
        "bmapp": myicp.bymMiniApp,  # 违法违规小程序
        "bkapp": myicp.bymKuaiApp,  # 违法违规快应用
    }

    app = web.Application()

    if config.proxy.local_ipv6_pool.enable:
        app.on_startup.append(init_ipv6_pool)
    elif config.proxy.tunnel.url is None:
        if config.proxy.extra_api.url is not None:
            if is_valid_url(config.proxy.extra_api.url):
                if config.proxy.extra_api.auto_maintenace:
                    logger.info("自动维护本地地址池"
                            f"提取间隔：{config.proxy.extra_api.extra_interval}秒 ，"
                            f"超时时间：{config.proxy.extra_api.timeout} 秒 ，"
                            f"提前丢弃：{config.proxy.extra_api.timeout_drop} 秒 ")
                    app.on_startup.append(init_proxy_pool)
                    app.on_cleanup.append(cleanup_proxy_pool)
            else:
                logger.warning("当前启用了API提取代理，但该地址似乎无效，将不使用该代理")

    aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(get_resource_path("templates")))
    app.add_routes(routes)
    app["tasks"] = {}
    
    # 初始化数据库
    app["db"] = Database()

    print('''
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃                      🎗️  赞助商                           ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
┌──────────────────────────────────────────────────────────┐
│  ☁️  林枫云                                               │
│  ├─ 企业级业务云、专业高频游戏云提供商                   │
│  └─ 🌐 https://www.dkdun.cn                              │
└──────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────┐
│  🚀  ANT PING                                            │
│  ├─ 一站式网络检测工具                                   │
│  └─ 🌐 https://antping.com                               │
└──────────────────────────────────────────────────────────┘
''')
    
    app.middlewares.append(options_middleware)
    if config.system.web_ui:
        print(f"\nweb ui: http://{'127.0.0.1' if config.system.host == '0.0.0.0' else config.system.host}:{config.system.port}\n\n"
              "按两次 Ctrl + C 可以退出程序\n")
    
    # 将LogCollector处理器添加到root logger
    collector_handler = CollectorHandler(log_collector)
    collector_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s - %(message)s', '%Y-%m-%d %H:%M:%S')
    collector_handler.setFormatter(formatter)
    logging.getLogger().addHandler(collector_handler)
    
    # 启动时添加日志
    logger.info(f"服务启动 - 监听地址: {config.system.host}:{config.system.port}")
    logger.info(f"验证码识别: {'启用' if config.captcha.enable else '禁用'}")
    
    web.run_app(app, host=config.system.host, port=config.system.port)
