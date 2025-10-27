"""
代理池管理模块
负责代理的获取、验证和维护
"""
import asyncio
import random
from datetime import datetime
import aiohttp
from cachetools import TTLCache
from mlog import logger
from load_config import config


# 代理池缓存
pool_cache = TTLCache(
    maxsize=config.proxy.extra_api.pool_num, 
    ttl=config.proxy.extra_api.timeout - config.proxy.extra_api.timeout_drop
)


class ProxyPool:
    """代理池管理类"""
    def __init__(self):
        # 获取代理地址的接口
        self.proxy_url = config.proxy.extra_api.url
        # 代理剩余多少秒时丢弃
        self.discard = config.proxy.extra_api.timeout_drop
        # 多少秒获取一次代理
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
        """向后兼容的启动方法"""
        await self.start()

    async def _init_session(self):
        """初始化HTTP会话"""
        if self.session is None:
            timeout = aiohttp.ClientTimeout(total=config.system.http_client_timeout)
            self.session = aiohttp.ClientSession(timeout=timeout)

    async def _close_session(self):
        """关闭HTTP会话"""
        if self.session is not None:
            await self.session.close()
            self.session = None

    async def _update(self):
        """获取新的代理到代理地址池"""
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

    async def cron_update(self):
        """定时任务,更新地址池"""
        try:
            while True:
                await self._update()
                await asyncio.sleep(self.period)
        except asyncio.CancelledError:
            logger.info("代理池更新任务已取消")
            raise

    async def getproxy(self, num=1):
        """获取代理"""
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


# IPv6地址池相关函数
async def init_ipv6_pool(app):
    """初始化IPv6地址池"""
    from utils import get_local_ipv6_addresses, configure_ipv6_addresses, is_public_ipv6
    
    logger.info("启用本地IPv6轮询")
    local_ipv6_addresses = get_local_ipv6_addresses()
    public_ipv6_addresses = [addr for addr in local_ipv6_addresses if is_public_ipv6(addr)]
    if len(public_ipv6_addresses) < config.proxy.local_ipv6_pool.pool_num:
        prefix = ":".join(public_ipv6_addresses[0].split(":")[0:4])  # 获取前四位作为前缀
        configure_ipv6_addresses(
            prefix, 
            config.proxy.local_ipv6_pool.pool_num - len(public_ipv6_addresses), 
            config.proxy.local_ipv6_pool.ipv6_network_card
        )
        logger.info(f"已配置 {config.proxy.local_ipv6_pool.pool_num - len(public_ipv6_addresses)} 个新的IPv6地址")
    else:
        logger.info("已有足够的IPv6地址，无需配置")
    asyncio.create_task(check_and_update_ipv6_pool())


async def check_and_update_ipv6_pool():
    """检查并更新IPv6地址池"""
    from utils import get_local_ipv6_addresses, configure_ipv6_addresses, is_public_ipv6
    
    while True:
        local_ipv6_addresses = get_local_ipv6_addresses()
        public_ipv6_addresses = [addr for addr in local_ipv6_addresses if is_public_ipv6(addr)]
        if len(public_ipv6_addresses) < config.proxy.local_ipv6_pool.pool_num:
            prefix = ":".join(public_ipv6_addresses[0].split(":")[0:4])  # 获取前四位作为前缀
            configure_ipv6_addresses(
                prefix, 
                config.proxy.local_ipv6_pool.pool_num - len(public_ipv6_addresses), 
                config.proxy.local_ipv6_pool.ipv6_network_card
            )
            logger.info(f"已补充 {config.proxy.local_ipv6_pool.pool_num - len(public_ipv6_addresses)} 个新的IPv6地址")
        await asyncio.sleep(config.proxy.local_ipv6_pool.check_interval)


async def init_proxy_pool_task(app):
    """初始化代理池任务（用于app启动时）"""
    if not hasattr(app, "proxypool"):
        app.proxypool = ProxyPool()
        await app.proxypool.start()
        logger.info("初始化地址池维护任务")


async def cleanup_proxy_pool_task(app):
    """清理代理池任务（用于app关闭时）"""
    if hasattr(app, "proxypool"):
        await app.proxypool.stop()
        logger.info("清理地址池维护任务")

