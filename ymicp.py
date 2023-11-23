'''
author           : Yiming
Creat time       : 2023/9/8 16:53
modification time: 2023/11/23 19:37
Blog             : https://www.cnblogs.com/ymer
Github           : https://github.com/HG-ha
Home             : https://api.wer.plus
QQ group         : 376957298,1029212047
'''

import asyncio
import aiohttp
import time
import hashlib
import ujson

class beian():
    def __init__(self):
        self.typj = {
            0:ujson.dumps(
                {'pageNum': '', 'pageSize': '', 'unitName': '',"serviceType":1}
                ), # 网站
            1:ujson.dumps(
                {"pageNum":"","pageSize":"","unitName":'',"serviceType":6}
                ), # APP
            2:ujson.dumps(
                {'pageNum': '', 'pageSize': '', 'unitName': '',"serviceType":7}
                ), # 小程序
            3:ujson.dumps(
                {'pageNum': '', 'pageSize': '', 'unitName': '',"serviceType":8}
                ) # 快应用
        }
        self.base_header = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.41 Safari/537.36 Edg/101.0.1210.32',
                'Origin': 'https://beian.miit.gov.cn',
                'Referer': 'https://beian.miit.gov.cn/'
            }
        self.btypj = {
            0: ujson.dumps({"domainName":""}),
            1: ujson.dumps({"serviceName":"","serviceType":6}),
            2: ujson.dumps({"serviceName":"","serviceType":7}),
            3: ujson.dumps({"serviceName":"","serviceType":8})
        }
        self.cookie_headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.41 Safari/537.36 Edg/101.0.1210.32'}
        self.home = 'https://beian.miit.gov.cn'
        self.url = 'https://hlwicpfwc.miit.gov.cn/icpproject_query/api/auth'
        # 正常查询
        self.queryByCondition = 'https://hlwicpfwc.miit.gov.cn/icpproject_query/api/icpAbbreviateInfo/queryByCondition'
        # 违法违规域名查询
        self.blackqueryByCondition = 'https://hlwicpfwc.miit.gov.cn/icpproject_query/api/blackListDomain/queryByCondition'
        # 违法违规APP,小程序,快应用
        self.blackappAndMiniByCondition = 'https://hlwicpfwc.miit.gov.cn/icpproject_query/api/blackListDomain/queryByCondition_appAndMini'

    async def _init_session(self):
        self.session = aiohttp.ClientSession()
    
    async def _close_session(self):
        if self.session is not None:
            await self.session.close()
    
    async def get_token(self):
        timeStamp = round(time.time()*1000)
        authSecret = 'testtest' + str(timeStamp)
        authKey = hashlib.md5(authSecret.encode(encoding='UTF-8')).hexdigest()
        self.auth_data = {'authKey': authKey, 'timeStamp': timeStamp}
        try:
            async with self.session.post(self.url,data=self.auth_data,headers=self.base_header) as req:
                t = ujson.loads(await req.text())
                self.base_header.update({'Token': t['params']['bussiness'], 'Accept':'application/json'})
        except Exception as e:
            print('error', e)
            return e

    async def get_cookie(self):
        async with self.session.get(self.home,headers=self.cookie_headers) as req:
            self.base_header.update({'Cookie': dict(req.headers.items())['Set-Cookie'].split(';')[0]})

    async def getbeian(self,name,sp,pageNum,pageSize,):
        info = ujson.loads(self.typj.get(sp))
        info['pageNum'] = pageNum
        info['pageSize'] = pageSize
        info['unitName'] = name
        await self.get_token()
        await self.get_cookie()
        async with self.session.post(self.queryByCondition, json=info, headers=self.base_header) as req:
            res = await req.text()
            return ujson.loads(res)
        
    async def getblackbeian(self,name,sp):
        info = ujson.loads(self.btypj.get(sp))
        if sp == 0:
            info['domainName'] = name
        else:
            info['serviceName'] = name
        await self.get_token()
        await self.get_cookie()
        async with self.session.post(
            self.blackqueryByCondition if sp == 0 else self.blackappAndMiniByCondition, 
                                     json=info, headers=self.base_header) as req:
            res = await req.text()
            return ujson.loads(res)

    async def autoget(self,name,sp,pageNum='',pageSize='',b=1):
        await self._init_session()
        try:
            data = await self.getbeian(name,sp,pageNum,pageSize) if b == 1 else await self.getblackbeian(name,sp)
        except Exception as e:
            print(e)
            return {"code":122,"msg":"查询失败"}
        finally:
            await self._close_session()

        if data['code'] == 500:
            return {"code":122,"msg":"工信部服务器异常"}
        return data

    # APP备案查询
    async def ymApp(self,name,pageNum=1,pageSize=10):
        return await self.autoget(name,1,pageNum,pageSize)

    # 网站备案查询
    async def ymWeb(self,name,pageNum=1,pageSize=10):
        return await self.autoget(name,0,pageNum,pageSize)

    # 小程序备案查询
    async def ymMiniApp(self,name,pageNum=1,pageSize=10):
        return await self.autoget(name,2,pageNum,pageSize)

    # 快应用备案查询
    async def ymKuaiApp(self,name,pageNum=1,pageSize=10):
        return await self.autoget(name,3,pageNum,pageSize)
    
    # 违法违规APP查询
    async def bymApp(self,name):
        return await self.autoget(name,1,b=0)

    # 违法违规网站查询
    async def bymWeb(self,name):
        return await self.autoget(name,0,b=0)

    # 违法违规小程序查询
    async def bymMiniApp(self,name):
        return await self.autoget(name,2,b=0)

    # 违法违规快应用查询
    async def bymKuaiApp(self,name):
        return await self.autoget(name,3,b=0)

if __name__ == '__main__':
    async def main():
        a = beian()
        # 官方单页查询pageSize最大支持26
        # 页面索引pageNum从1开始,第一页可以不写
        print(await a.ymWeb("深圳市腾讯计算机系统有限公司",pageSize=1)
    asyncio.run(main())

    '''
    在其他代码模块中调用（异步）

        from ymicp import beian

        icp = beian()
        data = await icp.ymApp("微信")
    
    '''
