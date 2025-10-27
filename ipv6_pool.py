"""
IPv6地址池管理模块
负责IPv6地址的获取、验证、维护和轮询
"""
import asyncio
import random
import time
import socket
import aiohttp
from typing import List, Optional
from mlog import logger
from load_config import config
from utils import get_local_ipv6_addresses, configure_ipv6_addresses, is_public_ipv6


class IPv6AddressPool:
    """IPv6地址池管理类"""
    
    def __init__(self):
        """初始化IPv6地址池"""
        self.active_addresses = {}  # {address: last_verified_time}
        self.system_addresses = []  # 系统中实际存在的地址列表
        self.lock = asyncio.Lock()
        self.pool_size = config.proxy.local_ipv6_pool.pool_num
        self.check_interval = config.proxy.local_ipv6_pool.check_interval
        self.network_card = config.proxy.local_ipv6_pool.ipv6_network_card
        self._maintenance_task = None
        self._last_prefix = None  # 记录上次的IPv6前缀
        
    async def initialize(self):
        """初始化地址池"""
        logger.info("初始化IPv6地址池...")
        
        # 获取系统中现有的IPv6地址
        await self._refresh_system_addresses()
        
        if not self.system_addresses:
            logger.error("未找到任何公网IPv6地址，无法启用IPv6池")
            return False
        
        # 提取IPv6前缀
        self._last_prefix = self._extract_prefix(self.system_addresses[0])
        logger.info(f"检测到IPv6前缀: {self._last_prefix}")
        
        # 验证现有地址的可用性
        logger.info(f"开始验证 {len(self.system_addresses)} 个系统IPv6地址的可用性...")
        verified_count = 0
        
        # 并发验证所有地址（限制并发数为5）
        semaphore = asyncio.Semaphore(5)
        
        async def verify_and_add(addr):
            nonlocal verified_count
            async with semaphore:
                # 首先检查网段是否为公网
                if not is_public_ipv6(addr):
                    logger.warning(f"IPv6地址不是公网地址（网段检测）: {addr}")
                    return False
                
                # 然后验证实际可达性
                if await self._verify_ipv6_address(addr):
                    self.active_addresses[addr] = time.time()
                    verified_count += 1
                    logger.info(f"✓ IPv6地址可用: {addr}")
                    return True
                else:
                    logger.warning(f"✗ IPv6地址不可用: {addr}")
                    return False
        
        # 并发验证所有地址
        tasks = [verify_and_add(addr) for addr in self.system_addresses]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        logger.info(f"验证完成：{verified_count}/{len(self.system_addresses)} 个地址可用")
        
        if verified_count == 0:
            logger.error("没有任何可用的公网IPv6地址，无法启用IPv6池")
            return False
        
        # 如果地址数量不足，自动补充
        if len(self.active_addresses) < self.pool_size:
            needed = self.pool_size - len(self.active_addresses)
            logger.info(f"当前有 {len(self.active_addresses)} 个可用IPv6地址，需要补充 {needed} 个")
            await self._add_addresses(needed)
        else:
            logger.info(f"已有 {len(self.active_addresses)} 个可用IPv6地址，满足需求")
        
        # 启动维护任务
        await self.start_maintenance()
        return True
    
    async def _refresh_system_addresses(self):
        """刷新系统中实际存在的IPv6地址"""
        all_addresses = get_local_ipv6_addresses()
        self.system_addresses = [addr for addr in all_addresses if is_public_ipv6(addr)]
        logger.debug(f"系统中有 {len(self.system_addresses)} 个公网IPv6地址")
    
    def _extract_prefix(self, address: str) -> str:
        """提取IPv6地址的前64位前缀"""
        parts = address.split(":")
        return ":".join(parts[0:4])
    
    async def _verify_ipv6_address(self, address: str) -> bool:
        """
        验证IPv6地址是否真的可用（公网可达）
        通过绑定指定IPv6地址访问 ifconfig.me，检查返回的IP是否匹配
        """
        try:
            # 创建一个绑定到指定IPv6地址的连接器
            connector = aiohttp.TCPConnector(
                family=socket.AF_INET6,
                local_addr=(address, 0),
                ssl=False
            )
            
            timeout = aiohttp.ClientTimeout(total=5)
            
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                # 使用 ifconfig.me 检测出口IP
                async with session.get('https://ifconfig.me/ip') as resp:
                    if resp.status == 200:
                        detected_ip = (await resp.text()).strip()
                        
                        # 检查返回的IP是否与指定的IPv6地址匹配
                        if detected_ip == address:
                            logger.debug(f"IPv6地址验证成功: {address}")
                            return True
                        else:
                            logger.warning(f"IPv6地址验证失败: {address}, 检测到的IP: {detected_ip}")
                            return False
                    else:
                        logger.warning(f"IPv6地址验证失败: {address}, HTTP状态码: {resp.status}")
                        return False
                        
        except asyncio.TimeoutError:
            logger.warning(f"IPv6地址验证超时: {address}")
            return False
        except Exception as e:
            logger.warning(f"IPv6地址验证出错: {address}, 错误: {e}")
            return False
    
    async def _add_addresses(self, count: int):
        """添加指定数量的IPv6地址（不再校验新地址，只要本地存在且为公网地址就加入池）"""
        if not self._last_prefix:
            logger.error("无法添加IPv6地址：未知前缀")
            return 0

        logger.info(f"尝试添加 {count} 个IPv6地址...")
        added = 0
        max_attempts = count * 3  # 最多尝试次数（考虑到可能有失败的）
        attempts = 0

        while added < count and attempts < max_attempts:
            attempts += 1
            try:
                # 生成新地址
                configure_ipv6_addresses(self._last_prefix, 1, self.network_card)
                await asyncio.sleep(0.5)  # 等待系统应用配置

                # 重新获取系统地址
                old_system_addresses = set(self.system_addresses)
                await self._refresh_system_addresses()

                # 找出新增的地址
                new_addresses = set(self.system_addresses) - old_system_addresses - set(self.active_addresses.keys())

                if new_addresses:
                    for new_addr in new_addresses:
                        # 只要本地存在且为公网地址就直接加入池
                        if is_public_ipv6(new_addr):
                            self.active_addresses[new_addr] = time.time()
                            logger.info(f"✓ 成功添加IPv6地址: {new_addr}")
                            added += 1
                            break
                        else:
                            logger.warning(f"新添加的IPv6地址不是公网地址: {new_addr}")
                else:
                    logger.warning(f"添加IPv6地址可能失败，未检测到新地址（尝试 {attempts}/{max_attempts}）")

            except Exception as e:
                logger.error(f"添加IPv6地址时出错: {e}")

            # 如果还需要继续添加，短暂等待
            if added < count:
                await asyncio.sleep(0.5)

        logger.info(f"添加完成：成功 {added}/{count} 个，共尝试 {attempts} 次")
        return added
    
    async def _cleanup_invalid_addresses(self):
        """清理失效的IPv6地址"""
        async with self.lock:
            # 刷新系统地址列表
            await self._refresh_system_addresses()
            system_addr_set = set(self.system_addresses)
            
            # 检查活跃池中的地址
            invalid_addresses = []
            for addr in list(self.active_addresses.keys()):
                if addr not in system_addr_set:
                    invalid_addresses.append(addr)
            
            # 移除失效地址
            if invalid_addresses:
                for addr in invalid_addresses:
                    del self.active_addresses[addr]
                    logger.warning(f"IPv6地址已失效，已移除: {addr}")
                logger.info(f"清理了 {len(invalid_addresses)} 个失效的IPv6地址")
            
            return len(invalid_addresses)
    
    async def _check_prefix_change(self):
        """检查IPv6前缀是否发生变化"""
        if not self.system_addresses:
            return False
        
        current_prefix = self._extract_prefix(self.system_addresses[0])
        if current_prefix != self._last_prefix:
            logger.warning(f"检测到IPv6前缀变化: {self._last_prefix} -> {current_prefix}")
            self._last_prefix = current_prefix
            
            # 清空活跃池，因为旧地址都失效了
            old_count = len(self.active_addresses)
            self.active_addresses.clear()
            
            # 重新添加系统中的地址
            for addr in self.system_addresses:
                if self._extract_prefix(addr) == current_prefix:
                    self.active_addresses[addr] = time.time()
            
            logger.info(f"前缀变化导致清理了 {old_count} 个旧地址，重新加载了 {len(self.active_addresses)} 个地址")
            return True
        
        return False
    
    async def maintain_pool(self):
        """维护地址池：清理失效地址并补充新地址"""
        try:
            # 1. 清理失效地址
            removed = await self._cleanup_invalid_addresses()
            
            # 2. 检查前缀是否变化
            prefix_changed = await self._check_prefix_change()
            
            # 3. 如果地址数量不足，补充新地址
            current_count = len(self.active_addresses)
            if current_count < self.pool_size:
                needed = self.pool_size - current_count
                logger.info(f"IPv6地址池不足，当前 {current_count}/{self.pool_size}，需要补充 {needed} 个")
                added = await self._add_addresses(needed)
                
                if added == 0 and current_count == 0:
                    logger.error("无法添加IPv6地址，地址池为空！")
            
            # 记录当前状态
            if removed > 0 or prefix_changed:
                logger.info(f"IPv6地址池维护完成：当前有 {len(self.active_addresses)} 个可用地址")
                
        except Exception as e:
            logger.error(f"维护IPv6地址池时出错: {e}")
    
    async def maintenance_loop(self):
        """地址池维护循环任务"""
        logger.info(f"IPv6地址池维护任务已启动，检查间隔: {self.check_interval}秒")
        
        while True:
            try:
                await asyncio.sleep(self.check_interval)
                await self.maintain_pool()
            except asyncio.CancelledError:
                logger.info("IPv6地址池维护任务已取消")
                break
            except Exception as e:
                logger.error(f"IPv6地址池维护任务出错: {e}")
                await asyncio.sleep(5)  # 出错后等待5秒再继续
    
    async def start_maintenance(self):
        """启动维护任务"""
        if self._maintenance_task is None or self._maintenance_task.done():
            self._maintenance_task = asyncio.create_task(self.maintenance_loop())
            logger.info("IPv6地址池维护任务已启动")
    
    async def stop_maintenance(self):
        """停止维护任务"""
        if self._maintenance_task and not self._maintenance_task.done():
            self._maintenance_task.cancel()
            try:
                await self._maintenance_task
            except asyncio.CancelledError:
                pass
            logger.info("IPv6地址池维护任务已停止")
    
    async def get_random_address(self) -> Optional[str]:
        """获取一个随机的IPv6地址"""
        async with self.lock:
            if not self.active_addresses:
                logger.error("IPv6地址池为空，无法获取地址")
                return None
            
            address = random.choice(list(self.active_addresses.keys()))
            logger.debug(f"使用IPv6地址: {address}")
            return address
    
    def get_address_count(self) -> int:
        """获取当前可用地址数量"""
        return len(self.active_addresses)
    
    def get_all_addresses(self) -> List[str]:
        """获取所有活跃地址"""
        return list(self.active_addresses.keys())


# 全局IPv6地址池实例
_ipv6_pool: Optional[IPv6AddressPool] = None


async def init_ipv6_pool(app):
    """初始化IPv6地址池（用于app启动时）"""
    global _ipv6_pool
    
    logger.info("启用本地IPv6地址池管理")
    _ipv6_pool = IPv6AddressPool()
    success = await _ipv6_pool.initialize()
    
    if success:
        app['ipv6_pool'] = _ipv6_pool
        logger.info(f"IPv6地址池初始化成功，当前有 {_ipv6_pool.get_address_count()} 个可用地址")
    else:
        logger.error("IPv6地址池初始化失败")
        app['ipv6_pool'] = None


async def cleanup_ipv6_pool(app):
    """清理IPv6地址池（用于app关闭时）"""
    global _ipv6_pool
    
    if _ipv6_pool:
        await _ipv6_pool.stop_maintenance()
        logger.info("IPv6地址池已清理")


def get_ipv6_pool() -> Optional[IPv6AddressPool]:
    """获取全局IPv6地址池实例"""
    return _ipv6_pool

