"""
工具函数模块
包含各种通用工具函数
"""
import re
import sys
import os
import subprocess
import locale
import uuid
from mlog import logger


def is_valid_url(url):
    """验证URL是否有效"""
    regex = re.compile(
        r'^(?:http)s?://'  # http:// or https:// or ftp://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}|'  # ...or ipv4
        r'\[?[A-F0-9]*:[A-F0-9:]+\]?)'  # ...or ipv6
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return re.match(regex, url) is not None


def get_resource_path(relative_path):
    """获取打包后的可执行文件中的资源文件路径"""
    if getattr(sys, 'frozen', False):  # 如果是打包后的程序
        app_path = os.path.dirname(sys.executable)
    else:
        app_path = os.path.dirname(os.path.abspath(__file__))

    return os.path.join(app_path, relative_path)


def is_public_ipv6(ipv6):
    """检查IPv6地址是否为公网IP"""
    return not (ipv6.startswith("fe80") or ipv6.startswith("fc00") or ipv6.startswith("fd00"))


def _run_cmd_capture(cmd):
    """执行系统命令并自动多编码尝试解码"""
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate(timeout=5)
    except Exception:
        return ""
    if not out:
        return ""
    enc_candidates = [
        "utf-8",
        locale.getpreferredencoding(False) or "",
        "gbk",
        "cp936",
        "latin-1",
    ]
    for enc in enc_candidates:
        if not enc:
            continue
        try:
            return out.decode(enc)
        except Exception:
            continue
    return out.decode("utf-8", errors="ignore")


def get_local_ipv6_addresses():
    """获取本地IPv6地址"""
    addresses = []
    try:
        if os.name == 'nt':
            output = _run_cmd_capture(["netsh", "interface", "ipv6", "show", "addresses"])
            if not output:
                return []
            for line in output.splitlines():
                line_strip = line.strip()
                if any(k in line_strip for k in ("公用", "手动", "Public", "Manual")) and ":" in line_strip:
                    parts = line_strip.split()
                    candidate = parts[-1].split("/")[0]
                    if ":" in candidate and is_public_ipv6(candidate):
                        addresses.append(candidate)
        else:
            output = _run_cmd_capture(["ip", "-6", "addr", "show"])
            if not output:
                return []
            for line in output.splitlines():
                line_strip = line.strip()
                if ("inet6" in line_strip) and ("scope global" in line_strip):
                    try:
                        candidate = line_strip.split()[1].split("/")[0]
                        if is_public_ipv6(candidate):
                            addresses.append(candidate)
                    except:
                        continue
    except Exception:
        return []
    return list(dict.fromkeys(addresses))


def configure_ipv6_addresses(prefix, count, adapter_name):
    """配置指定数量的IPv6地址"""
    if os.name == 'nt':  # Windows
        for _ in range(count):
            guid = uuid.uuid4().hex
            new_temp_ipv6 = f"{prefix}:{guid[:4]}:{guid[4:8]}:{guid[8:12]}:{guid[12:16]}"
            subprocess.run([
                "netsh", "interface", "ipv6", "add", "address", adapter_name, new_temp_ipv6,
                "store=active", "skipassource=true"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:  # Linux
        for _ in range(count):
            guid = uuid.uuid4().hex
            new_temp_ipv6 = f"{prefix}:{guid[:4]}:{guid[4:8]}:{guid[8:12]}:{guid[12:16]}"
            subprocess.run([
                "ip", "-6", "addr", "add", new_temp_ipv6, "dev", adapter_name
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

