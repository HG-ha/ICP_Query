# -*- coding: utf-8 -*-
"""
任务管理器模块
用于管理异步任务和信号量
"""
import asyncio
import weakref
import signal
import sys
from mlog import logger


class TaskManager:
    """全局任务管理器"""

    def __init__(self):
        self._tasks = weakref.WeakValueDictionary()
        self._semaphores = {}
        self._shutdown_event = asyncio.Event()

    def add_task(self, task_name, task):
        """添加任务"""
        self._tasks[task_name] = task

    def get_task(self, task_name):
        """获取任务"""
        return self._tasks.get(task_name)

    def remove_task(self, task_name):
        """移除任务"""
        if task_name in self._tasks:
            task = self._tasks[task_name]
            if not task.done():
                task.cancel()
            del self._tasks[task_name]

    def get_semaphore(self, name, limit):
        """获取信号量"""
        if name not in self._semaphores:
            self._semaphores[name] = asyncio.Semaphore(limit)
        return self._semaphores[name]

    async def _async_shutdown(self):
        """异步关闭所有任务"""
        logger.info("开始关闭所有任务...")
        for task_name in list(self._tasks.keys()):
            self.remove_task(task_name)
        # 等待任务完成
        await asyncio.sleep(1)
        logger.info("所有任务已关闭")
        self._shutdown_event.set()

    async def shutdown(self):
        """公共的异步关闭方法"""
        if not self._shutdown_event.is_set():
            await self._async_shutdown()


def setup_signal_handlers(task_manager):
    """设置信号处理器"""
    loop = None
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = None

    def signal_handler(sig, frame):
        if sig == signal.SIGINT:
            logger.warning('收到关闭信号，程序停止')
            if loop and loop.is_running():
                # 创建 shutdown 任务并等待完成
                shutdown_task = loop.create_task(task_manager.shutdown())
                # 使用 call_soon 来确保任务被调度
                def wait_for_shutdown():
                    async def wait():
                        try:
                            await asyncio.wait_for(shutdown_task, timeout=5.0)
                        except asyncio.TimeoutError:
                            logger.warning("关闭任务超时，强制退出")
                        except Exception as e:
                            logger.error(f"关闭任务异常：{e}")
                        finally:
                            sys.exit(0)
                    loop.create_task(wait())
                loop.call_soon_threadsafe(wait_for_shutdown)
            else:
                # 同步路径直接退出
                for task_name in list(task_manager._tasks.keys()):
                    task_manager.remove_task(task_name)
                sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
