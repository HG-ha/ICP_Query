# -*- coding: utf-8 -*-
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


def check_has_permanent_ipv6():
    """
    检查系统中是否存在永久有效的IPv6地址（valid_lft forever）
    返回: (has_permanent, sample_address)
    """
    try:
        if os.name == 'nt':
            # Windows下检查 SkipAsSource=False 的地址（永久地址通常是这样配置的）
            output = _run_cmd_capture(["netsh", "interface", "ipv6", "show", "addresses"])
            if output:
                for line in output.splitlines():
                    line_strip = line.strip()
                    # Windows下永久地址通常显示为 "手动" 或 "Manual"
                    if any(k in line_strip for k in ("手动", "Manual")) and ":" in line_strip:
                        parts = line_strip.split()
                        candidate = parts[-1].split("/")[0]
                        if ":" in candidate and is_public_ipv6(candidate):
                            return (True, candidate)
        else:
            # Linux下检查 valid_lft forever 的地址
            output = _run_cmd_capture(["ip", "-6", "addr", "show"])
            if output:
                lines = output.splitlines()
                for i, line in enumerate(lines):
                    line_strip = line.strip()
                    if ("inet6" in line_strip) and ("scope global" in line_strip):
                        try:
                            candidate = line_strip.split()[1].split("/")[0]
                            if is_public_ipv6(candidate):
                                # 检查下一行是否包含 valid_lft forever
                                if i + 1 < len(lines):
                                    next_line = lines[i + 1].strip()
                                    if "valid_lft forever" in next_line:
                                        return (True, candidate)
                        except:
                            continue
    except Exception as e:
        logger.debug(f"检测永久IPv6地址时出错: {e}")
    return (False, None)


def get_network_interfaces():
    """
    获取系统网卡列表
    返回: [{"name": "网卡名称", "display": "显示名称"}]
    """
    interfaces = []
    try:
        if os.name == 'nt':  # Windows
            # 使用 netsh 获取网卡列表
            output = _run_cmd_capture(["netsh", "interface", "show", "interface"])
            if output:
                lines = output.splitlines()
                for line in lines[3:]:  # 跳过前3行标题
                    parts = line.split()
                    if len(parts) >= 4:
                        # 格式: 状态 类型 接口名称
                        # 获取接口名称（最后一个字段可能包含空格）
                        interface_name = ' '.join(parts[3:])
                        if interface_name and interface_name not in ['Loopback', '环回']:
                            interfaces.append({
                                "name": interface_name,
                                "display": f"{interface_name}"
                            })
        else:  # Linux/Unix
            # 使用 ip link 获取网卡列表
            output = _run_cmd_capture(["ip", "link", "show"])
            if output:
                for line in output.splitlines():
                    if ':' in line and not line.startswith(' '):
                        # 格式: 2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP>
                        parts = line.split(':')
                        if len(parts) >= 2:
                            interface_name = parts[1].strip()
                            if interface_name and interface_name != 'lo':
                                interfaces.append({
                                    "name": interface_name,
                                    "display": interface_name
                                })
    except Exception as e:
        logger.debug(f"获取网卡列表时出错: {e}")
    
    return interfaces


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

