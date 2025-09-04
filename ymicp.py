import asyncio
import aiohttp
import cv2
import time
import hashlib
import re
import base64
import os
import numpy as np
import ujson
import random
import uuid
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from detnate import detnate
from aiohttp import TCPConnector
from mlog import logger
import warnings
warnings.filterwarnings("ignore", category=UserWarning)
import ssl
import subprocess
import locale

ssl._create_default_https_context = ssl._create_unverified_context()

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

def load_config(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        data = yaml.safe_load(file)

    return Config(**data)

config = load_config('config.yml')

def is_public_ipv6(ipv6):
    return not (ipv6.startswith("fe80") or ipv6.startswith("fc00") or ipv6.startswith("fd00"))

# 获取本地IPv6地址
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
    """跨平台获取本机公网IPv6地址，自动处理编码/异常"""
    addresses = []
    try:
        if os.name == 'nt':  # Windows
            output = _run_cmd_capture(["netsh", "interface", "ipv6", "show", "addresses"])
            if not output:
                return []
            for line in output.splitlines():
                line_strip = line.strip()
                # 兼容中文(公用/手动)及可能的英文(Public/Manual)
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
        # 违法违规APP,小程序,快应用
        self.blackappAndMiniByCondition = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/blackListDomain/queryByCondition_appAndMini"
        # 新增：APP/小程序/快应用详情查询接口
        self.queryDetailByAppAndMiniId = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/icpAbbreviateInfo/queryDetailByAppAndMiniId"
        self.sign = "eyJ0eXBlIjozLCJleHREYXRhIjp7InZhZnljb2RlX2ltYWdlX2tleSI6IjUyZWI1ZTcyODViNzRmNWJhM2YwYzBkNTg0YTg3NmVmIn0sImUiOjE3NTY5NzAyNDg4MjN9.Ngpkwn4T7sQoQF9pCk_sQQpH61wQUEKnK2sQ8hDIq-Q"
        self.token = ""
        self.token_expire = 0
        self.det = detnate()
        self.timeout = aiohttp.ClientTimeout(total=config.system.http_client_timeout)
        self.local_ipv6_addresses = get_local_ipv6_addresses() if config.proxy.local_ipv6_pool.enable else []

    async def get_session(self, proxy=""):
        if proxy:
            return aiohttp.ClientSession(timeout=self.timeout, connector=TCPConnector(ssl=False))
        elif self.local_ipv6_addresses:
            
            local_ipv6 = random.choice(self.local_ipv6_addresses)
            connector = TCPConnector(ssl=False, local_addr=(local_ipv6, 0))
            return aiohttp.ClientSession(timeout=self.timeout, connector=connector)
        else:
            return aiohttp.ClientSession(timeout=self.timeout, connector=TCPConnector(ssl=False))

    async def get_token(self, proxy=""):
        base_header = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.41 Safari/537.36 Edg/101.0.1210.32",
                    "Origin": "https://beian.miit.gov.cn",
                    "Referer": "https://beian.miit.gov.cn/",
                    "Cookie": f"__jsluid_s=948698cf319a8abdedca50a59c9faf05" if not config.captcha.enable else f"__jsluid_s={await self.get_cookie(proxy)}",
                    "Accept": "application/json, text/plain, */*",
                }
        if self.token_expire > int(time.time() * 1000):
            return True,self.token,base_header
        
        timeStamp = round(time.time() * 1000)
        authSecret = "testtest" + str(timeStamp)
        authKey = hashlib.md5(authSecret.encode(encoding="UTF-8")).hexdigest()
        auth_data = {"authKey": authKey, "timeStamp": timeStamp}
        
        try:
            async with await self.get_session(proxy) as session:
                async with session.post(self.url, data=auth_data, headers=base_header, proxy=proxy if proxy else None) as req:
                    req = await req.text()

            if "当前访问疑似黑客攻击" in req:
                return False,"当前访问已被创宇盾拦截",""
            t = ujson.loads(req)
            self.token = t["params"]["bussiness"]
            self.token_expire = int(time.time() * 1000) + t["params"]["expire"]
            return True,self.token, base_header
        except Exception as e:
            return False,str(e),""

    async def get_cookie(self, proxy=""):
        async with await self.get_session(proxy) as session:
            async with session.get(self.home, headers=self.cookie_headers, proxy=proxy if proxy else None) as req:
                res = await req.text()
                return re.compile("[0-9a-z]{32}").search(str(req.cookies))[0]

    # 进行aes加密
    def get_pointJson(self, value, key):
        cipher = AES.new(key.encode(), AES.MODE_ECB)
        ciphertext = cipher.encrypt(pad(ujson.dumps(value).encode(), AES.block_size))
        ciphertext_base64 = base64.b64encode(ciphertext)
        return ciphertext_base64.decode("utf-8")

    # 新增的UID加密生成算法
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

    async def check_img(self, proxy=""):
        success, token, base_header = await self.get_token(proxy)
        if not success:
            logger.info(f"获取token失败：{token}")
            return False, token,'','',''
        try:
            data = self.get_clientUid()
            clientUid = ujson.loads(data)["clientUid"]
            length = str(len(str(data).encode("utf-8")))
            base_header.update({"Content-Length": length, "Token": token})
            base_header["Content-Type"] = "application/json"
            try:
                async with await self.get_session(proxy) as session:
                    async with session.post(self.getCheckImage, data=data, headers=base_header, proxy=proxy if proxy else None) as req:
                        res = await req.json()
            except Exception as e:
                logger.info(f"请求验证码时失败：{e}")
                return False, f"请求验证码时失败：{e}",'','',''
            
            p_uuid = res["params"]["uuid"]
            big_image = res["params"]["bigImage"]
            small_image = res["params"]["smallImage"]
            secretKey = res["params"]["secretKey"]
            wordCount = res["params"]["wordCount"]
            start = time.time()
            success,selice_small = await self.small_selice(small_image, big_image)
            if not success:
                logger.info(f"验证码切割失败：{selice_small}")
                return False, "selice_small",'','',''
            logger.info(f"预测用时 {time.time() - start} s")

            pointJson = self.get_pointJson(selice_small, secretKey)
            data = ujson.loads(
                ujson.dumps(
                    {
                        "token": p_uuid,
                        "secretKey": secretKey,
                        "clientUid": clientUid,
                        "pointJson": pointJson,
                    }
                )
            )
            length = str(len(str(data).encode("utf-8")))
            base_header.update({"Content-Length": length})
            async with await self.get_session(proxy) as session:
                async with session.post(self.checkImage, json=data, headers=base_header, proxy=proxy if proxy else None) as req:
                    res = await req.text()
            data = ujson.loads(res)
            if data["success"] == False:
                if config.captcha.save_failed_img:
                    folder_paths = [f'{config.captcha.save_failed_img_path}/ibig',
                                     f'{config.captcha.save_failed_img_path}/isma']
                    for folder in folder_paths:
                        os.makedirs(folder, exist_ok=True)

                    isma = cv2.imdecode(
                        np.frombuffer(base64.b64decode(small_image), np.uint8), cv2.COLOR_GRAY2RGB
                    )

                    ibig = cv2.imdecode(
                        np.frombuffer(base64.b64decode(big_image), np.uint8), cv2.COLOR_GRAY2RGB
                    )
                    
                    filename = f"{uuid.uuid4()}.jpg"
                    isma_image_name = f"{config.captcha.save_failed_img_path}/isma/{filename}"
                    ibig_image_name = f"{config.captcha.save_failed_img_path}/ibig/{filename}"
                    logger.info(f"保存到：{isma_image_name}，{ibig_image_name}")
                    cv2.imwrite(isma_image_name,isma)
                    cv2.imwrite(ibig_image_name,ibig)
                return False, "验证码识别失败",'','',''
            else:
                return True, p_uuid, token, data["params"]["sign"], base_header
            
        except Exception as e:
            logger.warning(f"check_image Faile : {e}")
            return False

    async def small_selice(self, small_image, big_image):
        isma = cv2.imdecode(
            np.frombuffer(base64.b64decode(small_image), np.uint8), cv2.COLOR_GRAY2RGB
        )

        isma = cv2.cvtColor(isma, cv2.COLOR_BGRA2BGR) # 测试完注释
        ibig = cv2.imdecode(
            np.frombuffer(base64.b64decode(big_image), np.uint8), cv2.COLOR_GRAY2RGB
        )

        if config.captcha.coding_code == 'labour':
            def mouse_callback(event, x, y, flags, param):
                if event == cv2.EVENT_LBUTTONDOWN:
                    data.append({"x":x,"y":y})
                    if len(data) == 4:
                        cv2.destroyAllWindows()
            data = []
            # 确保两个图像的通道数量一致
            if ibig.shape[2] != isma.shape[2]:
                if ibig.shape[2] == 1:
                    ibig = cv2.cvtColor(ibig, cv2.COLOR_GRAY2BGR)
                elif ibig.shape[2] == 4 and isma.shape[2] == 3:
                    isma = cv2.cvtColor(isma, cv2.COLOR_BGR2BGRA)
                elif ibig.shape[2] == 3 and isma.shape[2] == 4:
                    ibig = cv2.cvtColor(ibig, cv2.COLOR_BGR2BGRA)
                elif ibig.shape[2] == 3 and isma.shape[2] == 1:
                    isma = cv2.cvtColor(isma, cv2.COLOR_GRAY2BGR)
                elif ibig.shape[2] == 1 and isma.shape[2] == 3:
                    ibig = cv2.cvtColor(ibig, cv2.COLOR_GRAY2BGR)
            width = min(ibig.shape[1], isma.shape[1]) 
            ibig_resized = cv2.resize(ibig, (width, int(ibig.shape[0] * (width / ibig.shape[1])))) 
            isma_resized = cv2.resize(isma, (width, int(isma.shape[0] * (width / isma.shape[1]))))
            new_image = np.vstack((ibig_resized, isma_resized))
            cv2.imshow('Please click in order', new_image)
            cv2.setMouseCallback('Please click in order', mouse_callback)
            cv2.waitKey(0)
            return True, data
        else:
            success,data = self.det.check_target(ibig, isma)
            return success,data

    async def getAppAndMiniDetail(self, dataId, serviceType, p_uuid, token, sign, base_header, proxy=""):
        """获取 APP / 小程序 / 快应用 详细信息（复用一次打码验证结果）"""
        info = {"dataId": dataId, "serviceType": serviceType}
        length = str(len(str(ujson.dumps(info, ensure_ascii=False)).encode("utf-8")))

        detail_header = base_header.copy()
        detail_header.update({"Content-Length": length, "Uuid": p_uuid, "Token": token, "Sign": sign})

        if not config.captcha.enable:
            detail_header.pop("Uuid", None)
            detail_header.pop("Content-Length", None)

        async with await self.get_session(proxy) as session:
            if config.captcha.enable:
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
        if config.captcha.enable:
            success, p_uuid, token, sign, base_header = await self.check_img(proxy)
            if not success:
                logger.info(f"打码失败：{p_uuid}")
                return False, p_uuid

            length = str(len(str(ujson.dumps(info, ensure_ascii=False)).encode("utf-8")))
            base_header.update({"Content-Length": length, "Uuid": p_uuid, "Token": token, "Sign": sign})
            async with await self.get_session(proxy) as session:
                async with session.post(self.queryByCondition,
                                        data=ujson.dumps(info, ensure_ascii=False),
                                        headers=base_header,
                                        proxy=proxy if proxy else None) as req:
                    res = await req.text()
        else:
            success,token,base_header = await self.get_token(proxy)
            sign = ""
            p_uuid = ""
            if not success:
                logger.info(f"获取token失败")
                return False, None
            base_header.update({"Token":token,"Sign":self.sign})

            async with await self.get_session(proxy) as session:
                async with session.post(f"{self.queryByCondition}/",
                                        json=info,
                                        headers=base_header,
                                        proxy=proxy if proxy else None) as req:
                    res = await req.text()

        if "当前访问疑似黑客攻击" in res:
            return False,"当前访问已被创宇盾拦截"
        
        result = ujson.loads(res)

        # 并发获取详情（仅 APP / 小程序 / 快应用）
        if (sp in (1, 2, 3)
            and result.get("success")
            and result.get("params", {}).get("list")):
            items = result["params"]["list"]
            logger.info(f"需要并发获取详细信息数量: {len(items)}")
            sem = asyncio.Semaphore(getattr(getattr(config, "system", object()), "detail_concurrency", 5))

            async def fetch_detail(item):
                if "dataId" not in item:
                    return item
                serviceType = 6 if sp == 1 else (7 if sp == 2 else 8)
                try:
                    async with sem:
                        d_success, d_data = await self.getAppAndMiniDetail(
                            item["dataId"], serviceType, p_uuid, token, sign if config.captcha.enable else self.sign, base_header, proxy
                        )
                    if d_success and d_data.get("success"):
                        return d_data["params"]
                    else:
                        logger.warning(f"详情获取失败 dataId={item.get('dataId')}")
                        return item
                except Exception as e:
                    logger.error(f"详情获取异常 dataId={item.get('dataId')} err={e}")
                    return item

            tasks = [fetch_detail(it) for it in items]
            detailed_list = await asyncio.gather(*tasks)
            result["params"]["list"] = detailed_list
            logger.info(f"并发详情完成，总计 {len(detailed_list)} 条")
        return True, result
    
    async def getblackbeian(self, name, sp, proxy=""):
        info = ujson.loads(self.btypj.get(sp))
        if sp == 0:
            info["domainName"] = name
        else:
            info["serviceName"] = name

        success, p_uuid, token, sign, base_header = await self.check_img(proxy)
        if not success:
            return False, p_uuid
        
        length = str(len(str(ujson.dumps(info, ensure_ascii=False)).encode("utf-8")))
        base_header.update(
            {"Content-Length": length, "Uuid": p_uuid, "Token": token, "Sign": sign}
        )
        async with await self.get_session(proxy) as session:
            async with session.post((self.blackqueryByCondition if sp == 0 else self.blackappAndMiniByCondition), data=ujson.dumps(info, ensure_ascii=False), headers=base_header, proxy=proxy if proxy else None) as req:
                res = await req.text()
        return True,ujson.loads(res)

    async def autoget(self, name, sp, pageNum="", pageSize="", proxy="", b=1):
        try:
            if proxy != "":
                success,data = (
                    await self.getbeian(name, sp, pageNum, pageSize, proxy)
                    if b == 1
                    else await self.getblackbeian(name, sp, proxy)
                )
            else:
                success,data = (
                    await self.getbeian(name, sp, pageNum, pageSize)
                    if b == 1
                    else await self.getblackbeian(name, sp)
                )
            if not success:
                return {"code":500,"message":data}
            if data["code"] == 500 or not success:
                return {"code": 122, "message": "工信部服务器异常"}
        except Exception as e:
            return {"code": 122, "message": "查询失败","error":str(e)}
        
        return data

    # APP备案查询
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

    # 违法违规APP查询
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


if __name__ == "__main__":

    async def main():
        a = beian()
        # 官方单页查询pageSize最大支持26
        # 页面索引pageNum从1开始,第一页可以不写
        data = await a.ymWeb("深圳市腾讯计算机系统有限公司")
        print(f"查询结果：\n{data}")
        data = await a.ymApp("深圳市腾讯计算机系统有限公司")
        print(f"查询结果：\n{data}")

    asyncio.run(main())

    """
    在其他代码模块中调用（异步）

        from ymicp import beian

        icp = beian()
        data = await icp.ymApp("微信")
    
    """
