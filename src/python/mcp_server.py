# -*- coding: utf-8 -*-
"""
ICP_Query MCP Server
- stdio:  python mcp_server.py
- http:   python mcp_server.py --http [--port 16182]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any, Optional

# 保证可从任意 cwd 导入同目录模块
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ICP_Query")

QUERY_HANDLERS = {
    "web": "ymWeb",
    "app": "ymApp",
    "mapp": "ymMiniApp",
    "kapp": "ymKuaiApp",
    "bweb": "bymWeb",
    "bapp": "bymApp",
    "bmapp": "bymMiniApp",
    "bkapp": "bymKuaiApp",
}


def _allowed_types() -> list:
    try:
        from load_config import config
        return list(getattr(config.risk_avoidance, "allow_type", None) or list(QUERY_HANDLERS.keys()))
    except Exception:
        return list(QUERY_HANDLERS.keys())


@mcp.tool()
async def icp_query_types() -> str:
    """返回当前允许的 ICP 查询类型列表（web/app/mapp/kapp 及黑名单类型）。"""
    return json.dumps({"allow_type": _allowed_types()}, ensure_ascii=False)


@mcp.tool()
async def icp_query(
    type: str,
    search: str,
    page_num: Optional[int] = 1,
    page_size: Optional[int] = 10,
) -> str:
    """查询中国工信部 ICP 备案信息。

    Args:
        type: 查询类型，web=网站, app=APP, mapp=小程序, kapp=快应用,
              bweb/bapp/bmapp/bkapp=对应黑名单查询
        search: 域名 / 单位名称 / 备案号 / 应用名等关键词
        page_num: 页码，从 1 开始（黑名单类型忽略）
        page_size: 每页条数，最大建议 26（黑名单类型忽略）
    """
    qtype = (type or "").strip().lower()
    keyword = (search or "").strip()
    if not keyword:
        return json.dumps({"code": 101, "message": "search 不能为空"}, ensure_ascii=False)
    if qtype not in QUERY_HANDLERS:
        return json.dumps(
            {"code": 102, "message": f"不支持的类型: {qtype}", "allow_type": list(QUERY_HANDLERS)},
            ensure_ascii=False,
        )
    allowed = _allowed_types()
    if qtype not in allowed:
        return json.dumps(
            {"code": 102, "message": f"类型未被配置允许: {qtype}", "allow_type": allowed},
            ensure_ascii=False,
        )

    from ymicp import beian

    client = beian()
    try:
        method = getattr(client, QUERY_HANDLERS[qtype])
        if qtype.startswith("b"):
            result = await method(keyword)
        else:
            result = await method(keyword, page_num or 1, page_size or 10)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"code": 500, "message": str(e)}, ensure_ascii=False)
    finally:
        try:
            await client.cleanup()
        except Exception:
            pass


def run_stdio() -> None:
    mcp.run(transport="stdio")


def run_http(host: str = "0.0.0.0", port: int = 16182) -> None:
    # FastMCP streamable-http；路径一般为 /mcp
    mcp.run(transport="streamable-http", host=host, port=port)


def main(argv: Optional[list] = None) -> None:
    parser = argparse.ArgumentParser(description="ICP_Query MCP Server")
    parser.add_argument("--http", action="store_true", help="使用 Streamable HTTP 而非 stdio")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)

    if args.http:
        port = args.port
        if port is None:
            try:
                from load_config import config
                port = int(getattr(getattr(config, "mcp", None), "port", 16182) or 16182)
            except Exception:
                port = 16182
        # 日志走 stderr，避免污染协议流
        print(f"MCP Streamable HTTP http://{args.host}:{port}/mcp", file=sys.stderr)
        run_http(host=args.host, port=port)
    else:
        run_stdio()


if __name__ == "__main__":
    main()
