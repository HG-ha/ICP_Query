# -*- coding: utf-8 -*-
from load_config import config
import logging
from logging.handlers import TimedRotatingFileHandler
import os

def create_logger(log_dir, log_filename, backup_count, log_level=logging.INFO):
    """
    创建一个日志记录器，支持日志文件按大小和按天分割。

    :param log_dir: 日志存放的目录
    :param log_filename: 日志文件名
    :param max_log_size: 单个日志文件的最大大小，单位是字节
    :param backup_count: 日志备份的数量，当日志文件切割时，保留多少个备份
    :param log_level: 日志级别，默认 INFO
    :return: 配置好的 logger
    """

    # 确保日志目录存在
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 日志文件的完整路径
    log_path = os.path.join(log_dir, log_filename)

    # 创建 logger 对象
    logger = logging.getLogger()

    # 设置日志级别
    logger.setLevel(log_level)
    # 创建日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    )

    if config.log.save_log:

        # 创建按天切割的日志处理器
        # TimedRotatingFileHandler 会按天切割日志
        timed_handler = TimedRotatingFileHandler(
            log_path, when="midnight", interval=1, backupCount=backup_count, encoding='utf-8'
        )
        timed_handler.setLevel(log_level)
        timed_handler.setFormatter(formatter)
        logger.addHandler(timed_handler)

    

    if config.log.output_console:
        # 添加控制台输出
        console_handler = logging.StreamHandler()  # 控制台处理器
        console_handler.setLevel(log_level)  # 设置控制台日志级别
        console_handler.setFormatter(formatter)  # 设置日志格式
        logger.addHandler(console_handler)  # 添加到 logger

    return logger

logger = create_logger(config.log.dir, f'{config.log.file_head}.log', config.log.backup_count)