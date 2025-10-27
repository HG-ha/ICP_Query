"""
路由模块
包含所有API路由
"""
from aiohttp import web


def setup_routes(app):
    """设置所有路由"""
    from .query_routes import setup_query_routes
    from .history_routes import setup_history_routes
    from .batch_routes import setup_batch_routes
    from .config_routes import setup_config_routes
    from .log_routes import setup_log_routes
    from .ui_routes import setup_ui_routes
    
    # 注册各模块路由
    setup_query_routes(app)
    setup_history_routes(app)
    setup_batch_routes(app)
    setup_config_routes(app)
    setup_log_routes(app)
    setup_ui_routes(app)

