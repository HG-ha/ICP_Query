# -*- coding: utf-8 -*-
"""
ICP备案查询系统 - 主入口文件
重构版本：模块化架构
"""
import sys
import io
import logging
from aiohttp import web
import aiohttp_jinja2
import jinja2

# 设置标准输出编码为UTF-8，避免在不同环境下出现编码错误
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 导入自定义模块
from mlog import logger
from load_config import config
from database import Database
from ymicp import beian
from utils import get_resource_path, is_valid_url
from task_manager import TaskManager, setup_signal_handlers
from log_collector import LogCollector, CollectorHandler, log_collector
from proxy_pool import init_proxy_pool_task, cleanup_proxy_pool_task
from ipv6_pool import init_ipv6_pool, cleanup_ipv6_pool
from middlewares import options_middleware, auth_middleware
from routes import setup_routes
from auth import auth_enabled


VERSION="0.7.0"


def print_banner():
    """打印启动横幅"""
    print('''
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
                         🎗️  赞助商                          
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

    ☁️  林枫云
    ├─ 企业级业务云、专业高频游戏云提供商
    └─ 🌐 https://www.dkdun.cn

    🚀  ANT PING
    ├─ 一站式网络检测工具
    └─ 🌐 https://antping.com

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
''')


def setup_logging():
    """设置日志系统"""
    collector_handler = CollectorHandler(log_collector)
    collector_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s - %(message)s', '%Y-%m-%d %H:%M:%S')
    collector_handler.setFormatter(formatter)
    logging.getLogger().addHandler(collector_handler)


def create_app():
    """创建并配置应用"""
    # 创建应用实例
    app = web.Application()
    
    # 初始化查询处理器
    myicp = beian()
    app['appth'] = {
        "web": myicp.ymWeb,      # 网站
        "app": myicp.ymApp,      # APP
        "mapp": myicp.ymMiniApp, # 小程序
        "kapp": myicp.ymKuaiApp, # 快应用
    }
    
    # 违法违规应用不支持翻页
    app['bappth'] = {
        "bweb": myicp.bymWeb,      # 违法违规网站
        "bapp": myicp.bymApp,      # 违法违规APP
        "bmapp": myicp.bymMiniApp, # 违法违规小程序
        "bkapp": myicp.bymKuaiApp, # 违法违规快应用
    }
    
    # 初始化任务管理
    app["tasks"] = {}
    app['task_manager'] = TaskManager()
    
    # 初始化数据库
    app["db"] = Database()
    
    # 设置模板
    aiohttp_jinja2.setup(app, loader=jinja2.FileSystemLoader(get_resource_path("templates")))
    
    # 配置静态文件服务
    from aiohttp import web as aio_web
    app.router.add_static('/static/', path=get_resource_path('static'), name='static')
    
    # 配置代理池
    if config.proxy.local_ipv6_pool.enable:
        app.on_startup.append(init_ipv6_pool)
        app.on_cleanup.append(cleanup_ipv6_pool)
    elif config.proxy.tunnel.url is None:
        if config.proxy.extra_api.url is not None:
            if is_valid_url(config.proxy.extra_api.url):
                if config.proxy.extra_api.auto_maintenace:
                    logger.info("自动维护本地地址池"
                            f"提取间隔：{config.proxy.extra_api.extra_interval}秒 ，"
                            f"超时时间：{config.proxy.extra_api.timeout} 秒 ，"
                            f"提前丢弃：{config.proxy.extra_api.timeout_drop} 秒 ")
                    app.on_startup.append(init_proxy_pool_task)
                    app.on_cleanup.append(cleanup_proxy_pool_task)
            else:
                logger.warning("当前启用了API提取代理，但该地址似乎无效，将不使用该代理")
    
    # 设置路由
    setup_routes(app)

    # 中间件：鉴权 -> CORS（aiohttp 列表前者为外层）
    app.middlewares.append(auth_middleware)
    app.middlewares.append(options_middleware)

    # 可选：启动 MCP Streamable HTTP（独立端口）
    mcp_cfg = getattr(config, "mcp", None)
    if mcp_cfg and getattr(mcp_cfg, "enable", False):
        app.on_startup.append(_start_mcp_http)
    
    return app


async def _start_mcp_http(app):
    """后台线程启动 MCP HTTP 服务"""
    import threading

    def _run():
        try:
            from mcp_server import run_http
            port = int(getattr(config.mcp, "port", 16182) or 16182)
            logger.info(f"MCP Streamable HTTP 启动于 0.0.0.0:{port}/mcp")
            run_http(host="0.0.0.0", port=port)
        except Exception as e:
            logger.error(f"MCP HTTP 启动失败: {e}")

    t = threading.Thread(target=_run, name="mcp-http", daemon=True)
    t.start()
    app["mcp_thread"] = t


def _parse_args(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=f"ICP_Query v{VERSION}")
    parser.add_argument("--mcp", action="store_true", help="以 MCP stdio 模式运行")
    parser.add_argument("--mcp-http", action="store_true", help="仅启动 MCP Streamable HTTP")
    parser.add_argument("--host", default=None, help="MCP HTTP 监听地址（默认 0.0.0.0）")
    parser.add_argument("--port", type=int, default=None, help="MCP HTTP 端口（默认读 config mcp.port）")
    return parser.parse_args(argv)


def main(argv=None):
    """主函数：默认 Web/API；--mcp / --mcp-http 与 Rust 对齐"""
    args = _parse_args(argv)

    if args.mcp or args.mcp_http:
        from mcp_server import run_http, run_stdio
        if args.mcp_http:
            host = args.host or "0.0.0.0"
            port = args.port
            if port is None:
                port = int(getattr(getattr(config, "mcp", None), "port", 16182) or 16182)
            print(f"MCP Streamable HTTP http://{host}:{port}/mcp", file=sys.stderr)
            run_http(host=host, port=port)
        else:
            # 日志走 stderr，避免污染 stdio 协议流
            run_stdio()
        return

    # 打印横幅
    print_banner()

    # 创建应用
    app = create_app()

    # 设置信号处理
    task_manager = app.get('task_manager')
    setup_signal_handlers(task_manager)

    # 设置日志
    setup_logging()

    # 输出启动信息
    if config.system.web_ui:
        print(f"\nweb ui: http://{'127.0.0.1' if config.system.host == '0.0.0.0' else config.system.host}:{config.system.port}\n\n"
              "按两次 Ctrl + C 可以退出程序\n")

    # 记录启动日志
    logger.info(f"服务启动 - 监听地址: {config.system.host}:{config.system.port}")
    logger.info(f"验证码识别: {'启用' if config.captcha.enable else '禁用'}")
    logger.info(f"账号认证: {'启用' if auth_enabled() else '禁用'}")
    mcp_cfg = getattr(config, "mcp", None)
    if mcp_cfg and getattr(mcp_cfg, "enable", False):
        logger.info(f"MCP HTTP: 启用 (端口 {getattr(mcp_cfg, 'port', 16182)})")

    # 启动服务
    web.run_app(app, host=config.system.host, port=config.system.port)


if __name__ == "__main__":
    main()
