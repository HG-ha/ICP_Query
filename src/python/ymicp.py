# -*- coding: utf-8 -*-
import asyncio
import aiohttp
import time
import hashlib
import re
import base64
import os
import io
import numpy as np
from PIL import Image
import ujson
import random
import uuid
from aiohttp import TCPConnector
from mlog import logger
import warnings
warnings.filterwarnings("ignore", category=UserWarning)
import ssl
import subprocess
import locale
from contextlib import asynccontextmanager
from load_config import config
from cachetools import TTLCache

ssl._create_default_https_context = ssl._create_unverified_context()


def is_public_ipv6(ipv6):
    return not (ipv6.startswith("fe80") or ipv6.startswith("fc00") or ipv6.startswith("fd00"))


# 获取本地 IPv6 地址
def _run_cmd_capture(cmd):
    """执行系统命令并自动多编码尝试解码，失败返回空字符串"""
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
    """跨平台获取本机公网 IPv6 地址，自动处理编码/异常"""
    addresses = []
    try:
        if os.name == 'nt':  # Windows
            output = _run_cmd_capture(["netsh", "interface", "ipv6", "show", "addresses"])
            if not output:
                return []
            for line in output.splitlines():
                line_strip = line.strip()
                # 兼容中文 (公用/手动) 及可能的英文 (Public/Manual)
                if any(k in line_strip for k in ("公用", "手动", "Public", "Manual")) and ":" in line_strip:
                    parts = line_strip.split()
                    candidate = parts[-1]
                    candidate = candidate.strip()
                    # 去除可能的/前缀长度
                    candidate = candidate.split("/")[0]
                    if ":" in candidate and is_public_ipv6(candidate):
                        addresses.append(candidate)
        else:  # Linux / mac
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
                    except Exception:
                        continue
    except Exception:
        return []
    # 去重
    return list(dict.fromkeys(addresses))


class beian:
    def __init__(self):
        self.typj = {
            0: ujson.dumps(
                {"pageNum": "", "pageSize": "", "unitName": "", "serviceType": 1}
            ),  # 网站
            1: ujson.dumps(
                {"pageNum": "", "pageSize": "", "unitName": "", "serviceType": 6}
            ),  # APP
            2: ujson.dumps(
                {"pageNum": "", "pageSize": "", "unitName": "", "serviceType": 7}
            ),  # 小程序
            3: ujson.dumps(
                {"pageNum": "", "pageSize": "", "unitName": "", "serviceType": 8}
            ),  # 快应用
        }
        self.btypj = {
            0: ujson.dumps({"domainName": ""}),
            1: ujson.dumps({"serviceName": "", "serviceType": 6}),
            2: ujson.dumps({"serviceName": "", "serviceType": 7}),
            3: ujson.dumps({"serviceName": "", "serviceType": 8}),
        }
        self.session = None
        self.cookie_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.41 Safari/537.36 Edg/101.0.1210.32"
        }
        self.home = "https://beian.miit.gov.cn/"
        self.url = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/auth"
        self.getCheckImage = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/image/getCheckImagePoint"
        self.checkImage = (
            "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/image/checkImage"
        )
        # 正常查询
        self.queryByCondition = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/icpAbbreviateInfo/queryByCondition"
        # 违法违规域名查询
        self.blackqueryByCondition = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/blackListDomain/queryByCondition"
        # 违法违规 APP,小程序，快应用
        self.blackappAndMiniByCondition = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/blackListDomain/queryByCondition_appAndMini"
        # APP/小程序/快应用详情查询接口
        self.queryDetailByAppAndMiniId = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/icpAbbreviateInfo/queryDetailByAppAndMiniId"
        self.sign = "eyJ0eXBlIjozLCJleHREYXRhIjp7InZhZnljb2RlX2ltYWdlX2tleSI6IjUyZWI1ZTcyODViNzRmNWJhM2YwYzBkNTg0YTg3NmVmIn0sImUiOjE3NTY5NzAyNDg4MjN9.Ngpkwn4T7sQoQF9pCk_sQQpH61wQUEKnK2sQ8hDIq-Q"
        self.token = ""
        self.token_expire = 0
        self.timeout = aiohttp.ClientTimeout(total=getattr(getattr(config, 'system', object()), 'http_client_timeout', 30))
        self.local_ipv6_addresses = get_local_ipv6_addresses() if getattr(getattr(getattr(config, 'proxy', object()), 'local_ipv6_pool', object()), 'enable', False) else []
        self.ipv6_index = 0

        # Bug 1 & 9 修复：使用 asyncio.Lock 替代 threading.Lock
        self._ipv6_lock = asyncio.Lock()  # IPv6 轮询锁

        # 连接池配置
        # Bug 10 修复：优化连接器配置，减少 keepalive 超时时间，启用关闭连接清理
        self.connector_config = {
            'limit': 100,
            'limit_per_host': 30,
            'ttl_dns_cache': 300,
            'use_dns_cache': True,
            'ssl': False,
            'keepalive_timeout': 15,  # 从 30 秒减少到 15 秒
            'enable_cleanup_closed': True  # Bug 3 修复：启用关闭连接的清理
        }

        self._blocked_ip_cache = TTLCache(maxsize=1000, ttl=300)
        # Bug 1 & 5 修复：使用 asyncio.Lock 替代 threading.Lock
        self._blocked_ip_lock = asyncio.Lock()

        # 用于跟踪当前正在使用的 IPv6 地址（用于被拦截时的索引计算）
        self._last_used_ipv6_index = -1

    # Bug 5 修复：异步黑名单操作方法
    async def _add_blocked_ip(self, ip):
        """异步添加 IP 到黑名单缓存"""
        if not ip:
            return
        async with self._blocked_ip_lock:
            self._blocked_ip_cache[ip] = True
            logger.info(f"IP {ip} 被创宇盾拦截已添加到黑名单缓存，5 分钟后恢复使用")

    async def _is_ip_blocked(self, ip):
        """异步检查 IP 是否在黑名单缓存中"""
        if not ip:
            return False
        async with self._blocked_ip_lock:
            return ip in self._blocked_ip_cache

    # Bug 2 & 9 修复：异步 IPv6 轮询，修复索引越界和原子性问题
    async def _get_next_ipv6(self):
        """异步 IPv6 轮询，跳过被拦截的 IP"""
        if not self.local_ipv6_addresses:
            return None

        async with self._ipv6_lock:
            # Bug 2 修复：检查地址列表长度变化
            if not self.local_ipv6_addresses:
                return None

            # Bug 2 修复：确保索引在有效范围内
            if self.ipv6_index >= len(self.local_ipv6_addresses):
                self.ipv6_index = 0

            attempts = 0
            max_attempts = len(self.local_ipv6_addresses) * 2  # 最多尝试两轮

            while attempts < max_attempts:
                # Bug 2 修复：使用模运算防止越界
                current_ipv6 = self.local_ipv6_addresses[self.ipv6_index]
                self.ipv6_index = (self.ipv6_index + 1) % len(self.local_ipv6_addresses)
                attempts += 1

                # Bug 9 修复：在锁内检查黑名单，确保原子性
                if not (current_ipv6 in self._blocked_ip_cache):
                    self._last_used_ipv6_index = (self.ipv6_index - 1) % len(self.local_ipv6_addresses)
                    return current_ipv6
                else:
                    logger.debug(f"跳过被拦截的 IPv6 地址：{current_ipv6}")

            logger.warning("所有 IPv6 地址都被拦截，暂无可用地址")
            return None

    async def _get_connector(self, local_ipv6=None):
        if local_ipv6:
            connector = TCPConnector(
                local_addr=(local_ipv6, 0),
                **self.connector_config
            )
        else:
            connector = TCPConnector(**self.connector_config)

        return connector

    @asynccontextmanager
    async def get_session(self, proxy=""):
        local_ipv6 = None
        if not proxy and self.local_ipv6_addresses:
            local_ipv6 = await self._get_next_ipv6()
            if local_ipv6:
                logger.info(f"使用本地 IPv6 地址：{local_ipv6}")

        # 为每个 session 创建独立的连接器
        connector = await self._get_connector(local_ipv6)

        session = aiohttp.ClientSession(
            timeout=self.timeout,
            connector=connector,
            headers={'Connection': 'keep-alive'}
        )

        try:
            yield session
        finally:
            # Bug 8 修复：完善异常处理，确保 session 和 connector 都被正确关闭
            try:
                await session.close()
            except Exception:
                pass
            try:
                await connector.close()
            except Exception:
                pass

    async def get_token(self, proxy=""):
        base_header = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.41 Safari/537.36 Edg/101.0.1210.32",
            "Origin": "https://beian.miit.gov.cn",
            "Referer": "https://beian.miit.gov.cn/",
            "Cookie": f"__jsluid_s={uuid.uuid4().hex}",
            "Accept": "application/json, text/plain, */*",
        }

        if self.token_expire > int(time.time() * 1000):
            return True, self.token, base_header

        timeStamp = round(time.time() * 1000)
        authSecret = "testtest" + str(timeStamp)
        authKey = hashlib.md5(authSecret.encode(encoding="UTF-8")).hexdigest()
        auth_data = {"authKey": authKey, "timeStamp": timeStamp}

        try:
            async with self.get_session(proxy) as session:
                current_ip = None
                if hasattr(session, '_connector') and hasattr(session._connector, '_local_addr'):
                    current_ip = session._connector._local_addr[0] if session._connector._local_addr else None
                async with session.post(self.url, data=auth_data, headers=base_header, proxy=proxy if proxy else None) as req:
                    req_text = await req.text()

                    if "当前访问疑似黑客攻击" in req_text:
                        if current_ip:
                            await self._add_blocked_ip(current_ip)
                        elif not proxy and self.local_ipv6_addresses:
                            # Bug 9 修复：使用异步方式获取被拦截的 IPv6 索引
                            if self._last_used_ipv6_index >= 0:
                                blocked_ip = self.local_ipv6_addresses[self._last_used_ipv6_index]
                                await self._add_blocked_ip(blocked_ip)
                        return False, "当前访问已被创宇盾拦截", ""

                    t = ujson.loads(req_text)
                    token = t["params"]["bussiness"]
                    expire = int(time.time() * 1000) + t["params"]["expire"]

                    self.token = token
                    self.token_expire = expire

                    return True, token, base_header
        except Exception as e:
            logger.warning(f"get_token Faile : {e}")
            return False, str(e), ""

    async def get_cookie(self, proxy=""):
        async with await self.get_session(proxy) as session:
            async with session.get(self.home, headers=self.cookie_headers, proxy=proxy if proxy else None) as req:
                res = await req.text()
                return re.compile("[0-9a-z]{32}").search(str(req.cookies))[0]

    def get_clientUid(self):
        characters = "0123456789abcdef"
        unique_id = ["0"] * 36

        for i in range(36):
            unique_id[i] = random.choice(characters)

        unique_id[14] = "4"
        unique_id[19] = characters[(3 & int(unique_id[19], 16)) | 8]
        unique_id[8] = unique_id[13] = unique_id[18] = unique_id[23] = "-"

        point_id = "point-" + "".join(unique_id)

        return ujson.dumps({"clientUid": point_id})

    def match_slider_offset(self, small_image_b64, big_image_b64):
        """在大图上找与滑块同尺寸的纯色正方形缺口区域，返回其 x 偏移量（亚毫秒优化版）"""
        small_bytes = base64.b64decode(small_image_b64)
        big_bytes = base64.b64decode(big_image_b64)

        # 小图只取尺寸，避免完整解码像素
        with Image.open(io.BytesIO(small_bytes)) as sm:
            sw, sh = sm.size

        big_img = np.asarray(Image.open(io.BytesIO(big_bytes)).convert("RGB"))
        # 下采样 + 量化一步完成
        resized = big_img[::2, ::2]
        h, w = resized.shape[:2]
        min_side = max(1, int(min(sw, sh) * 0.25))
        skip_left = sw // 4
        good_enough = (min_side * min_side * 3) // 2

        q = (resized.astype(np.int32) & ~3)
        color_id = q[:, :, 0] + q[:, :, 1] * 256 + q[:, :, 2] * 65536

        flat = color_id.ravel()
        unique, counts = np.unique(flat, return_counts=True)
        # 只检查 Top-3 高频色
        top_indices = np.argpartition(counts, max(-3, -len(counts)))[-3:]

        best_area = 0
        best_x = 0
        col_run = np.empty((h, w), dtype=np.int32)

        for idx in top_indices:
            c = unique[idx]
            mask = color_id == c
            col_run[0] = mask[0]
            for y in range(1, h):
                col_run[y] = (col_run[y - 1] + 1) * mask[y]

            for y in range(min_side, h):
                row = col_run[y]
                x = skip_left
                while x < w:
                    if row[x] < min_side:
                        x += 1
                        continue
                    s = x
                    while x < w and row[x] >= min_side:
                        x += 1
                    run_w = x - s
                    run_h = int(row[s])
                    if run_h > 0:
                        ratio = run_w / run_h
                        area = run_w * run_h
                        if 0.7 < ratio < 1.4 and area > best_area:
                            best_area = area
                            best_x = s
                            if best_area >= good_enough:
                                offset_x = best_x * 2
                                logger.info(f"缺口定位：x={offset_x}, 滑块={sw}x{sh}")
                                return True, offset_x

        if best_area == 0:
            return False, "未找到缺口"

        offset_x = best_x * 2
        logger.info(f"缺口定位：x={offset_x}, 滑块={sw}x{sh}")
        return True, offset_x

    async def check_img(self, proxy=""):
        success, token, base_header = await self.get_token(proxy)
        if not success:
            logger.info(f"获取 token 失败：{token}")
            return False, token, '', '', ''
        try:
            data = self.get_clientUid()
            length = str(len(str(data).encode("utf-8")))
            base_header.update({"Content-Length": length, "token": token})
            base_header["Content-Type"] = "application/json"
            try:
                async with self.get_session(proxy) as session:
                    async with session.post(self.getCheckImage, data=data, headers=base_header, proxy=proxy if proxy else None) as req:
                        res = await req.json()
            except Exception as e:
                logger.info(f"请求验证码时失败：{e}")
                return False, f"请求验证码时失败：{e}", '', '', ''

            p_uuid = res["params"]["uuid"]
            big_image = res["params"]["bigImage"]
            small_image = res["params"]["smallImage"]

            start = time.time()
            match_success, offset_x = self.match_slider_offset(small_image, big_image)
            if not match_success:
                logger.info(f"滑块匹配失败：{offset_x}")
                return False, "滑块匹配失败", '', '', ''
            logger.info(f"滑块匹配用时 {(time.time() - start) * 1000:.3f}ms")

            check_data = ujson.dumps({"key": p_uuid, "value": str(offset_x)})
            logger.info(f"checkImage 请求体：{check_data}")
            length = str(len(check_data.encode("utf-8")))
            base_header.update({"Content-Length": length})
            async with self.get_session(proxy) as session:
                async with session.post(self.checkImage, data=check_data, headers=base_header, proxy=proxy if proxy else None) as req:
                    res = await req.text()

            data = ujson.loads(res)
            logger.info(f"checkImage 响应：code={data.get('code')}, msg={data.get('msg')}, success={data.get('success')}")
            if not data.get("success", False):
                captcha_config = getattr(config, 'captcha', object())
                if getattr(captcha_config, 'save_failed_img', False):
                    save_path = getattr(captcha_config, 'save_failed_img_path', './failed_captcha')
                    for folder in [f'{save_path}/ibig', f'{save_path}/isma']:
                        os.makedirs(folder, exist_ok=True)
                    filename = f"{uuid.uuid4()}.jpg"
                    with open(f"{save_path}/isma/{filename}", "wb") as f:
                        f.write(base64.b64decode(small_image))
                    with open(f"{save_path}/ibig/{filename}", "wb") as f:
                        f.write(base64.b64decode(big_image))
                    logger.info(f"失败验证码已保存：{filename}")
                return False, "验证码识别失败", '', '', ''
            else:
                sign = data["params"]
                return True, p_uuid, token, sign, base_header

        except Exception as e:
            logger.warning(f"check_image Faile : {e}")
            return False, str(e), '', '', ''

    async def getAppAndMiniDetail(self, dataId, serviceType, p_uuid, token, sign, base_header, proxy=""):
        """优化的详情获取，移除会话复用"""
        info = {"dataId": dataId, "serviceType": serviceType}
        length = str(len(str(ujson.dumps(info, ensure_ascii=False)).encode("utf-8")))

        detail_header = base_header.copy()
        detail_header.update({"Content-Length": length, "uuid": p_uuid, "token": token, "sign": sign})

        if not getattr(getattr(config, 'captcha', object()), 'enable', False):
            detail_header.pop("uuid", None)
            detail_header.pop("Content-Length", None)

        # Bug 7 修复：始终创建独立会话，避免会话复用与连接器冲突
        async with self.get_session(proxy) as session:
            if getattr(getattr(config, 'captcha', object()), 'enable', False):
                async with session.post(self.queryDetailByAppAndMiniId,
                    data=ujson.dumps(info, ensure_ascii=False),
                    headers=detail_header,
                    proxy=proxy if proxy else None) as req:
                    res = await req.text()
            else:
                async with session.post(f"{self.queryDetailByAppAndMiniId}",
                    json=info,
                    headers=detail_header,
                    proxy=proxy if proxy else None) as req:
                    res = await req.text()

        return True, ujson.loads(res)

    async def getbeian(self, name, sp, pageNum, pageSize, proxy=""):
        info = ujson.loads(self.typj.get(sp))
        info["pageNum"] = pageNum
        info["pageSize"] = pageSize
        info["unitName"] = name

        if getattr(getattr(config, 'captcha', object()), 'enable', False):
            success, p_uuid, token, sign, base_header = await self.check_img(proxy)
            if not success:
                logger.info(f"打码失败：{p_uuid}")
                return False, p_uuid

            length = str(len(str(ujson.dumps(info, ensure_ascii=False)).encode("utf-8")))
            base_header.update({"Content-Length": length, "uuid": p_uuid, "token": token, "sign": sign})

            async with self.get_session(proxy) as session:
                async with session.post(self.queryByCondition,
                    data=ujson.dumps(info, ensure_ascii=False),
                    headers=base_header,
                    proxy=proxy if proxy else None) as req:
                    res = await req.text()
        else:
            success, token, base_header = await self.get_token(proxy)
            sign = ""
            p_uuid = ""
            if not success:
                logger.info(f"获取 token 失败")
                return False, None
            base_header.update({"token": token, "sign": self.sign})

            async with self.get_session(proxy) as session:
                current_ip = None
                if hasattr(session, '_connector') and hasattr(session._connector, '_local_addr'):
                    current_ip = session._connector._local_addr[0] if session._connector._local_addr else None
                async with session.post(f"{self.queryByCondition}/",
                    json=info,
                    headers=base_header,
                    proxy=proxy if proxy else None) as req:
                    res = await req.text()

                if "当前访问疑似黑客攻击" in res:
                    if current_ip:
                        await self._add_blocked_ip(current_ip)
                    elif not proxy and self.local_ipv6_addresses:
                        # Bug 9 修复：使用异步方式获取被拦截的 IPv6 索引
                        if self._last_used_ipv6_index >= 0:
                            blocked_ip = self.local_ipv6_addresses[self._last_used_ipv6_index]
                            await self._add_blocked_ip(blocked_ip)
                    return False, "当前访问已被创宇盾拦截"

        result = ujson.loads(res)

        # 并发详情获取
        if (sp in (1, 2, 3)
            and result.get("success")
            and result.get("params", {}).get("list")):

            items = result["params"]["list"]
            if not items:
                return True, result

            logger.info(f"需要并发获取详细信息数量：{len(items)}")

            # Bug 4 修复：优化并发控制，使用更合理的批处理策略
            max_concurrency = min(
                getattr(getattr(config, "system", object()), "detail_concurrency", 5),
                len(items),
                20  # 最大并发限制
            )

            # Bug 4 修复：使用更小的批次，减少连接竞争
            batch_size = max_concurrency

            async def fetch_detail(item):
                if "dataId" not in item:
                    return item

                serviceType = 6 if sp == 1 else (7 if sp == 2 else 8)
                try:
                    # 每个详情请求使用独立会话
                    d_success, d_data = await self.getAppAndMiniDetail(
                        item["dataId"], serviceType, p_uuid, token,
                        sign if getattr(getattr(config, 'captcha', object()), 'enable', False) else self.sign,
                        base_header, proxy
                    )

                    if d_success and d_data.get("success"):
                        return d_data["params"]
                    else:
                        logger.warning(f"详情获取失败 dataId={item.get('dataId')}")
                        return item
                except Exception as e:
                    logger.error(f"详情获取异常 dataId={item.get('dataId')} err={e}")
                    return item

            detailed_list = []

            # Bug 4 修复：分批处理，每批任务完成后等待完成
            for i in range(0, len(items), batch_size):
                batch = items[i:i + batch_size]
                tasks = [fetch_detail(item) for item in batch]
                batch_results = await asyncio.gather(*tasks, return_exceptions=True)

                # 处理异常结果
                for j, res in enumerate(batch_results):
                    if isinstance(res, Exception):
                        logger.error(f"批次任务异常：{res}")
                        detailed_list.append(batch[j])  # 返回原始数据
                    else:
                        detailed_list.append(res)

            result["params"]["list"] = detailed_list
            logger.info(f"并发详情完成，总计 {len(detailed_list)} 条")

        return True, result

    async def getblackbeian(self, name, sp, proxy=""):
        info = ujson.loads(self.btypj.get(sp))
        if sp == 0:
            info["domainName"] = name
        else:
            info["serviceName"] = name

        if getattr(getattr(config, 'captcha', object()), 'enable', False):
            success, p_uuid, token, sign, base_header = await self.check_img(proxy)
            if not success:
                return False, p_uuid

            length = str(len(str(ujson.dumps(info, ensure_ascii=False)).encode("utf-8")))
            base_header.update(
                {"Content-Length": length, "uuid": p_uuid, "token": token, "sign": sign}
            )
            async with self.get_session(proxy) as session:
                current_ip = None
                if hasattr(session, '_connector') and hasattr(session._connector, '_local_addr'):
                    current_ip = session._connector._local_addr[0] if session._connector._local_addr else None
                async with session.post((self.blackqueryByCondition if sp == 0 else self.blackappAndMiniByCondition),
                    data=ujson.dumps(info, ensure_ascii=False),
                    headers=base_header, proxy=proxy if proxy else None) as req:
                    res = await req.text()
        else:
            success, token, base_header = await self.get_token(proxy)
            sign = ""
            p_uuid = ""
            if not success:
                logger.info(f"获取 token 失败")
                return False, None
            base_header.update({"token": token, "sign": self.sign})

            async with self.get_session(proxy) as session:
                current_ip = None
                if hasattr(session, '_connector') and hasattr(session._connector, '_local_addr'):
                    current_ip = session._connector._local_addr[0] if session._connector._local_addr else None
                async with session.post((f"{self.blackqueryByCondition}/" if sp == 0 else f"{self.blackappAndMiniByCondition}/"),
                    json=info,
                    headers=base_header, proxy=proxy if proxy else None) as req:
                    res = await req.text()

                if "当前访问疑似黑客攻击" in res:
                    if current_ip:
                        await self._add_blocked_ip(current_ip)
                    elif not proxy and self.local_ipv6_addresses:
                        # Bug 9 修复：使用异步方式获取被拦截的 IPv6 索引
                        if self._last_used_ipv6_index >= 0:
                            blocked_ip = self.local_ipv6_addresses[self._last_used_ipv6_index]
                            await self._add_blocked_ip(blocked_ip)
                    return False, "当前访问已被创宇盾拦截"

        return True, ujson.loads(res)

    async def autoget(self, name, sp, pageNum="", pageSize="", proxy="", b=1):
        try:
            if proxy != "":
                success, data = (
                    await self.getbeian(name, sp, pageNum, pageSize, proxy)
                    if b == 1
                    else await self.getblackbeian(name, sp, proxy)
                )
            else:
                success, data = (
                    await self.getbeian(name, sp, pageNum, pageSize)
                    if b == 1
                    else await self.getblackbeian(name, sp)
                )
            if not success:
                return {"code": 500, "message": data}
            if data.get("code") == 500 or not success:
                return {"code": 122, "message": "工信部服务器异常"}
        except Exception as e:
            return {"code": 122, "message": "查询失败", "error": str(e)}

        return data

    # APP 备案查询
    async def ymApp(self, name, pageNum="", pageSize="", proxy=""):
        return await self.autoget(name, 1, pageNum, pageSize, proxy)

    # 网站备案查询
    async def ymWeb(self, name, pageNum="", pageSize="", proxy=""):
        return await self.autoget(name, 0, pageNum, pageSize, proxy)

    # 小程序备案查询
    async def ymMiniApp(self, name, pageNum="", pageSize="", proxy=""):
        return await self.autoget(name, 2, pageNum, pageSize, proxy)

    # 快应用备案查询
    async def ymKuaiApp(self, name, pageNum="", pageSize="", proxy=""):
        return await self.autoget(name, 3, pageNum, pageSize, proxy)

    # 违法违规 APP 查询
    async def bymApp(self, name, proxy=""):
        return await self.autoget(name, 1, b=0, proxy=proxy)

    # 违法违规网站查询
    async def bymWeb(self, name, proxy=""):
        return await self.autoget(name, 0, b=0, proxy=proxy)

    # 违法违规小程序查询
    async def bymMiniApp(self, name, proxy=""):
        return await self.autoget(name, 2, b=0, proxy=proxy)

    # 违法违规快应用查询
    async def bymKuaiApp(self, name, proxy=""):
        return await self.autoget(name, 3, b=0, proxy=proxy)

    async def cleanup(self):
        """清理资源"""
        logger.info("beian 资源清理完成")

    def __del__(self):
        """析构函数，确保资源清理"""
        try:
            pass
        except:
            pass


if __name__ == "__main__":
    async def main():
        a = beian()
        try:
            # 官方单页查询 pageSize 最大支持 26
            # 页面索引 pageNum 从 1 开始，第一页可以不写
            data = await a.ymWeb("深圳市腾讯计算机系统有限公司")
            print(f"查询结果：\n{data}")
            data = await a.ymApp("深圳市腾讯计算机系统有限公司")
            print(f"查询结果：\n{data}")
        finally:
            await a.cleanup()  # 确保资源清理

    asyncio.run(main())

    """
    在其他代码模块中调用（异步）

    from ymicp import beian

    icp = beian()
    try:
        data = await icp.ymApp("微信")
    finally:
        await icp.cleanup() # 重要：确保资源清理
    """