# -*- coding: utf-8 -*-
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

# Bug 2 修复：确保 TTL 不为负数
_proxy_ttl = max(1, config.proxy.extra_api.timeout - config.proxy.extra_api.timeout_drop)

# 代理池缓存
pool_cache = TTLCache(
    maxsize=config.proxy.extra_api.pool_num,
    ttl=_proxy_ttl
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
        # 代理池的统一 session
        self.session = None
        # 更新锁，防止并发更新
        self._update_lock = asyncio.Lock()
        # Bug 7 修复：添加代理检查锁
        self._check_lock = asyncio.Lock()
        # Bug 3 修复：添加代理池操作锁，解决全局缓存池的竞态条件
        self._pool_lock = asyncio.Lock()
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
        """初始化 HTTP 会话"""
        if self.session is None:
            timeout = aiohttp.ClientTimeout(total=config.system.http_client_timeout)
            self.session = aiohttp.ClientSession(timeout=timeout)

    async def _close_session(self):
        """关闭 HTTP 会话"""
        if self.session is not None:
            await self.session.close()
            self.session = None

    async def _update(self):
        """获取新的代理到代理地址池"""
        async with self._update_lock:
            # Bug 3 修复：使用锁保护代理池操作
            async with self._pool_lock:
                if len(pool_cache) >= self.number:
                    logger.info(f"代理池饱满，无需更新代理，当前池内数量：{len(pool_cache)}")
                    return

            try:
                await self._init_session()
                async with self.session.get(self.proxy_url) as req:
                    res = await req.text()
                    proxy_list = [p.strip() for p in res.split("\n") if p.strip()]

                if len(proxy_list) == 0:
                    logger.error("提取到的 IP 为 0")
                    return

                endtime = datetime.now().timestamp()

                if config.proxy.extra_api.check_proxy:
                    await self._check_and_add_proxies(proxy_list, endtime)
                else:
                    # Bug 3 修复：使用锁保护批量添加操作
                    async with self._pool_lock:
                        for address in proxy_list:
                            if len(pool_cache) >= self.number:
                                break
                            pool_cache[address] = endtime

                logger.info(f"更新代理池成功，当前代理数量：{len(pool_cache)}")

            except Exception as e:
                logger.error(f"更新代理池失败：{e}")

    async def _check_and_add_proxies(self, proxy_list, endtime):
        """并发检查代理可用性并添加到池中"""
        semaphore = asyncio.Semaphore(config.proxy.extra_api.check_proxy_num)

        async def check_proxy(address):
            async with semaphore:
                # Bug 3 修复：使用锁保护代理池检查和添加操作
                async with self._pool_lock:
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

                        # Bug 3 修复：再次检查并添加，确保原子性
                        async with self._pool_lock:
                            if len(pool_cache) < self.number:
                                pool_cache[address] = endtime
                                logger.info(f"入库代理成功：{address}")
                except Exception:
                    logger.info(f"入库检测代理不可用：{address}")

        # 使用 asyncio.gather 处理并发任务，添加异常处理
        tasks = [check_proxy(address) for address in proxy_list]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def cron_update(self):
        """定时任务，更新地址池"""
        try:
            while True:
                await self._update()
                await asyncio.sleep(self.period)
        except asyncio.CancelledError:
            logger.info("代理池更新任务已取消")
            raise

    # Bug 3 修复：获取代理时检查过期时间
    async def getproxy(self, num=1):
        """获取代理"""
        # 等待代理池有可用代理
        timeout = 30  # 30 秒超时
        start_time = asyncio.get_event_loop().time()

        while True:
            current_time = datetime.now().timestamp()
            # Bug 3 修复：使用锁保护代理池读取操作
            async with self._pool_lock:
                # 过滤掉已过期的代理
                valid_proxies = [
                    key for key, expire_time in pool_cache.items()
                    if expire_time > current_time
                ]
                if len(valid_proxies) != 0:
                    random_key = f"http://{random.choice(valid_proxies)}"
                    break

            if asyncio.get_event_loop().time() - start_time > timeout:
                raise TimeoutError("等待代理超时")
            await asyncio.sleep(0.1)

        return random_key


# IPv6 地址池相关函数已迁移到 ipv6_pool.py


async def init_proxy_pool_task(app):
    """初始化代理池任务（用于 app 启动时）"""
    if not hasattr(app, "proxypool"):
        app.proxypool = ProxyPool()
        await app.proxypool.start()
        logger.info("初始化地址池维护任务")


async def cleanup_proxy_pool_task(app):
    """清理代理池任务（用于 app 关闭时）"""
    if hasattr(app, "proxypool"):
        await app.proxypool.stop()
        logger.info("清理地址池维护任务")
