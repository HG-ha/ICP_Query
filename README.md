# ICP_Query
ICP备案查询，基于Python3.8，全异步构建的高性能ICP查询模块，直接从工业和信息化部政务服务平台抓取实时数据，支持Web、APP、小程序、快应用名称查询，支持根据备案号查询，同时提供简单易用的高性能接口，提供打包好的可执行程序


### 安装依赖
``` shell
# 可以使用低版本包，基本都包含需要的模块
pip install -r requirements.txt
```

### 使用查询模块
``` python
import asyncio
from ymicp import beian

async def main(name):
    icp = beian()
    query = await icp.ymApp(name)
    print(query)

asyncio.run(main("微信"))
```

### 使用icpApi查询接口
##### 1. 支持四种类型查询：
- 网站： web
- APP: app
- 小程序: mapp
- 快应用: kapp
##### 2. 请求
1. GET
    - URL: http://0.0.0.0:16181/query/{type}?search={name}
    - 示例: 查询域名 baidu.com 备案信息
      
        ```
        curl http://127.0.0.1:16181/query/web?search=baidu.com
        ```
    - 示例: 根据网站的备案号 京ICP证030173号 查询备案信息
      
        ```
        curl http://127.0.0.1:16181/query/web?search=京ICP证030173号
        ```
2. POST
   - headers : {"Content-Type": "application/json"}
   - URL: http://0.0.0.0:16181/query/{type}
   - Body: {"search": {name}}
   - 示例: 查询域名 baidu.com 备案信息
     
        ```
        curl -X POST -H "Content-Type: application/json" -d '{"search":"baidu.com"}' http://127.0.0.1:16181/query/web
        ```
    - 示例: 根据网站的备案号 京ICP证030173号 查询备案信息
      
        ```
        curl -X POST -H "Content-Type: application/json" -d '{"search":"京ICP证030173号"}' http://127.0.0.1:16181/query/web
        ```

##### 3. Linux 运行icpApi
1. 源代码运行
   
    ``` shell
    python3 icpApi.py
    ```
2. 独立程序运行
   
    ``` shell
    ./icpApi.bin
    ```
##### 4. Windows 运行icpApi
1. 源代码运行
   
    ``` cmd
    python3 icpApi.py
    ```
2. 独立程序直接双击运行

##### 5. 直接使用在线API
[API文档](http://api.wer.plus/inteface?id=6)


|  参数             |  说明                |
| --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ---------------- |
|  firstPage        |  第一页的序号        |
<br>
|  hasNextPage      |  是否有下一页        |
<br>
|  isFirstPage      |  是否最后一页        |
<br>
|  lastPage         |  据查询数量有多少页  |
<br>
|  pages            |  同lastPage          |
<br>
|  pageSize         |  每页几条数据        |
<br>
|  pageNum          |  第几页              |
<br>
|  nextPage         |  下一页的页面序号    |
<br>
|  total            |  同pages             |
<br>
|  domain           |  备案的域名          |
<br>
|  domainId         |  域名id              |
<br>
|  limitAccess      |  是否限制接入        |
<br>
|  mainLicence      |  ICP备案主体许可证号 |
<br>
|  natureName       |  主办单位性质        |
<br>
|  serviceLicence   |  ICP备案服务许可证号 |
<br>
|  unitName         |  主办单位名称        |
<br>
|  updateRecordTime |  审核通过日期        |
<br>
|  contentTypeName  |  服务前置审批项      |
    
### 请喝茶吗

| 支付宝                                                                                     | 微信                                                                                    | 群                |
| --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ---------------- |
| <img src="https://github.com/HG-ha/qinglong/blob/main/zfb.jpg?raw=true" title="" alt="zfb" width="120px" height="120px"> | <img title="" src="https://github.com/HG-ha/qinglong/blob/main/wx.png?raw=true" alt="wx" width="120px" height="120px"> | 一铭API：1029212047 |
|                                                                                       |                                                                                       | 镜芯科技：376957298   |



### 其他项目

[一铭API](https://api.wer.plus)
