# -*- coding: utf-8 -*-
"""
日志收集器模块
用于收集和管理系统运行时日志
"""
from collections import deque
import threading
from datetime import datetime
import logging


class LogCollector:
    """实时日志收集器"""
    def __init__(self, maxlen=1000):
        self.logs = deque(maxlen=maxlen)
        self.lock = threading.Lock()
    
    def add_log(self, message, level='INFO'):
        """添加日志"""
        with self.lock:
            self.logs.append({
                'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'message': message,
                'level': level
            })
    
    def get_logs(self, limit=500):
        """获取日志列表"""
        with self.lock:
            logs_list = list(self.logs)
            return logs_list[-limit:] if len(logs_list) > limit else logs_list
    
    def clear(self):
        """清空日志"""
        with self.lock:
            self.logs.clear()


class CollectorHandler(logging.Handler):
    """自定义日志处理器，将日志添加到LogCollector"""
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


# 创建全局日志收集器实例
log_collector = LogCollector()

