#### 项目仅限于学习交流逆向与验证码识别技术使用
### 关于本项目
1. ICP备案查询，基于Python，全异步构建的高性能ICP查询模块，支持分页查询
2. 直接从工业和信息化部政务服务平台抓取实时数据，支持Web、APP、小程序、快应用名称查询
3. 支持根据备案号查询，支持根据企业名称查询，支持违法违规域名、APP查询
4. 提供简单易用的高性能接口以及发行版程序
5. 禁止售卖本项目，禁止用于违法目的，开源目的仅用于学习交流验证码识别和js逆向技术

### 部署

- 添加独立配置文件，支持绕过（不稳定，随时可能和谐，但查询速度快）和自动识别验证码方式（稳定），支持配置多种代理方式，内置webui，更新最新的查询接口，适当优化模型性能，优化内部错误处理
1. docker部署
    ``` shell
    docker run -d -p 16181:16181 yiminger/ymicp:latest
    ```
2. 本地部署
    - release下载最新版
3. 源码部署
    ``` shell
    git clone https://github.com/HG-ha/ICP_Query.git
    cd ICP_Query
    uv init
    uv venv --python 3.11
    uv pip install -r requirements.txt
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
##### 1. 支持八种类型查询：
- 网站：web
- APP：app
- 小程序：mapp
- 快应用：kapp
- 违法违规网站：bweb
- 违法违规APP：bapp
- 违法违规小程序：bmapp
- 违法违规快应用：bkapp
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
    - 示例: 根据企业名称查询备案信息
      
        ```
        curl http://127.0.0.1:16181/query/web?search=深圳市腾讯计算机系统有限公司
        ```
    - 示例: 根据企业名称查询备案信息，每页20条数据，查询第3页
      
        ```
        curl http://127.0.0.1:16181/query/web?search=深圳市腾讯计算机系统有限公司&pageNum=3&pageSize=20
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
    - 示例: 根据企业名称查询备案信息
      
        ```
        curl -X POST -H "Content-Type: application/json" -d '{"search":"深圳市腾讯计算机系统有限公司"}' http://127.0.0.1:16181/query/web
        ```
    - 示例: 根据企业名称查询备案信息，每页20条数据，查询第3页
      
        ```
        curl -X POST -H "Content-Type: application/json" -d '{"search":"深圳市腾讯计算机系统有限公司","pageNum":3,"pageSize":20}' http://127.0.0.1:16181/query/web
        ```

### 参数说明
|  参数             |  说明                |
|  ----  | ----  |
|  lastPage         |  据查询数量有多少页  |
|  pages            |  同lastPage          |
|  pageSize         |  每页几条数据        |
|  pageNum          |  第几页              |
|  nextPage         |  下一页的页面序号    |
|  total            |  同pages             |
|  domain           |  备案的域名          |
|  domainId         |  域名id              |
|  limitAccess      |  是否限制接入        |
|  mainLicence      |  ICP备案主体许可证号 |
|  natureName       |  主办单位性质        |
|  serviceLicence   |  ICP备案服务许可证号 |
|  unitName         |  主办单位名称        |
|  updateRecordTime |  审核通过日期        |
|  contentTypeName  |  服务前置审批项      |
|  cityId           |  城市ID             |
|  countyId         |  区县ID             |
|  contentTypeName  |  内容类型           |
|  mainUnitAddress  |  主体地址           |
|  serviceName      |  服务名称(APP、小程序或快应用名称)  |
|  version          |  服务版本           |
|  blackListLevel  | 威胁等级,表示是否为违法违规应用，目前获得的等级为2时，表示暂无违法违规信息 |

### 其他资源
- 镜芯API：<https://api2.wer.plus/>
- 林枫云_站长首选云服务器：<https://www.dkdun.cn/>
- 在线查询ICP备案：<https://icp.show>

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=HG-ha/ICP_Query&type=Date)](https://star-history.com/#HG-ha/ICP_Query&Date)
