# -*- coding: utf-8 -*-
import os
import sys
import yaml


class Config:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            # 如果值是字典，则递归转换为对象
            if isinstance(value, dict):
                value = Config(**value)
            setattr(self, key, value)

    def __repr__(self):
        return str(self.__dict__)

    def __getattr__(self, name):
        return None


def _find_config_path(file_path='config.yml'):
    """按优先级查找配置文件"""
    candidates = [
        file_path,
        os.path.join(os.getcwd(), file_path),
    ]
    # src/python -> 仓库根
    here = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(here)
    if os.path.basename(here) == 'python' and os.path.basename(parent) == 'src':
        candidates.append(os.path.join(os.path.dirname(parent), file_path))
    candidates.append(os.path.join(here, file_path))

    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return file_path


def load_config(file_path='config.yml'):
    path = _find_config_path(file_path)
    with open(path, 'r', encoding='utf-8') as file:
        data = yaml.safe_load(file)
    return Config(**data)


try:
    config = load_config('config.yml')
except Exception:
    print("加载配置文件失败")
    sys.exit(1)
