# -*- coding: utf-8 -*-
"""
配置管理路由模块
处理系统配置相关的API
"""
import os
import sys
import shutil
import asyncio
from aiohttp import web
from middlewares import jsondump, wj
from load_config import config
from mlog import logger
from log_collector import log_collector
from utils import get_resource_path, get_network_interfaces


routes = web.RouteTableDef()


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
            "risk_avoidance": {
                "allow_type": getattr(config.risk_avoidance, 'allow_type', ["web", "app", "mapp", "kapp", "bweb", "bapp", "bmapp", "bkapp"]),
                "prohibit_suffix": getattr(config.risk_avoidance, 'prohibit_suffix', [])
            },
            "log": {
                "dir": config.log.dir,
                "file_head": config.log.file_head,
                "backup_count": config.log.backup_count,
                "save_log": config.log.save_log,
                "output_console": config.log.output_console
            },
            "history": {
                "save_query_history": getattr(config, 'history', None) and getattr(config.history, 'save_query_history', True)
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
                    "allow_type": data.get("risk_avoidance", {}).get("allow_type", ["web", "app", "mapp", "kapp", "bweb", "bapp", "bmapp", "bkapp"]),
                    "prohibit_suffix": data.get("risk_avoidance", {}).get("prohibit_suffix", [])
                },
                "log": {
                    "dir": data.get("log", {}).get("dir", "logs"),
                    "file_head": data.get("log", {}).get("file_head", "ymicp"),
                    "backup_count": int(data.get("log", {}).get("backup_count", 7)),
                    "save_log": bool(data.get("log", {}).get("save_log", False)),
                    "output_console": bool(data.get("log", {}).get("output_console", True))
                },
                "history": {
                    "save_query_history": bool(data.get("history", {}).get("save_query_history", True))
                }
            }
            
            # 备份原配置文件
            config_path = get_resource_path("config.yml")
            backup_path = get_resource_path("config.yml.backup")
            
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


@jsondump
@routes.view(r"/config/network-interfaces")
async def get_network_interfaces_api(request):
    """获取系统网卡列表"""
    try:
        interfaces = get_network_interfaces()
        return wj({"code": 200, "data": interfaces})
    except Exception as e:
        logger.error(f"获取网卡列表失败: {e}")
        return wj({"code": 500, "message": f"获取网卡列表失败: {str(e)}"})


@jsondump
@routes.view(r"/config/restart")
async def restart_service(request):
    """重启服务"""
    if request.method == "POST":
        try:
            logger.warning("收到重启服务请求，将在3秒后重启...")
            log_collector.add_log("收到重启服务请求，将在3秒后重启...")
            
            # 异步延迟重启，先返回响应
            async def delayed_restart():
                try:
                    await asyncio.sleep(3)
                    logger.warning("正在重启服务...")
                    
                    # 获取当前Python解释器和脚本路径
                    python = sys.executable
                    main_script = sys.argv[0]
                    restart_helper = get_resource_path('restart_helper.py')
                    
                    # 重启进程
                    if os.name == 'nt':  # Windows
                        import subprocess
                        
                        # 优先使用重启助手脚本
                        if os.path.exists(restart_helper):
                            # 使用重启助手脚本
                            subprocess.Popen(
                                [python, restart_helper],
                                creationflags=subprocess.CREATE_NEW_CONSOLE,
                                cwd=os.path.dirname(get_resource_path('.'))
                            )
                        else:
                            # 直接重启
                            subprocess.Popen(
                                [python, main_script],
                                cwd=os.path.dirname(os.path.abspath(main_script))
                            )
                        
                        # 等待新进程启动
                        await asyncio.sleep(1)
                        
                    else:  # Linux/Unix
                        # Linux使用execv直接替换进程
                        os.execv(python, [python] + sys.argv)
                    
                    # Windows: 优雅停止事件循环
                    logger.info("停止当前服务进程...")
                    loop = asyncio.get_event_loop()
                    
                    # 停止所有任务
                    for task in asyncio.all_tasks(loop):
                        task.cancel()
                    
                    # 停止事件循环
                    loop.stop()
                    
                except Exception as e:
                    logger.error(f"重启服务时出错: {e}")
            
            # 创建异步任务
            asyncio.create_task(delayed_restart())
            
            return wj({"code": 200, "message": "服务将在3秒后重启"})
            
        except Exception as e:
            logger.error(f"重启服务失败: {e}")
            return wj({"code": 500, "message": f"重启服务失败: {str(e)}"})


def setup_config_routes(app):
    """注册配置管理路由"""
    app.add_routes(routes)

