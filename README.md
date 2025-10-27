<p align="center">
  <h1 align="center">ICP_Query</h1>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11-blue?style=flat-square" alt="Python Version"/>
  <a href="https://github.com/HG-ha/ICP_Query">
    <img src="https://img.shields.io/github/v/tag/HG-ha/ICP_Query?label=version&style=flat-square&sort=semver" alt="Latest Version"/>
  </a>
  <a href="https://github.com/HG-ha/ICP_Query/releases">
    <img src="https://img.shields.io/github/downloads/HG-ha/ICP_Query/total?style=flat-square" alt="GitHub Downloads"/>
  </a>
  <a href="https://hub.docker.com/repository/docker/yiminger/ymicp">
    <img src="https://img.shields.io/docker/pulls/yiminger/ymicp?logo=docker&style=flat-square" alt="Docker Pulls">
  </a>
</p>

> **注意：** 开源目的仅学习交流逆向与验证码识别技术使用

## 📋 关于本项目

- ✅ ICP备案查询，基于Python，全异步构建的高性能ICP查询模块，支持分页查询
- ✅ 直接从工业和信息化部政务服务平台抓取实时数据，支持Web、APP、小程序、快应用名称查询
- ✅ 支持根据备案号查询，支持根据企业名称查询，支持违法违规域名、APP查询
- ✅ 提供简单易用的高性能接口以及发行版程序
- ✅ 可高度自定义的独立配置文件，适配多种代理和免代理方式
- ✅ 内置webui，默认开启，浏览器访问 [http://127.0.0.1:16181](http://127.0.0.1:16181) 即可
- ✅ AMD 9600X 处理器平均识别仅需0.09s，支持模型加速

## 🎯 验证码识别效果
<div align="center">
  <img width="500" height="240" alt="image" src="https://github.com/user-attachments/assets/7acf9a45-c947-4dd0-9185-839e43b4483f" />
  <img width="500" height="240" alt="image" src="https://github.com/user-attachments/assets/e5fc2452-8d32-408d-adcd-f62f5c1bdc7f" />
  <img width="500" height="240" alt="image" src="https://github.com/user-attachments/assets/7cbfad57-186b-493c-8461-8475eca126ad" />
  <img width="500" height="240" alt="image" src="https://github.com/user-attachments/assets/b83f3238-b2e3-4f19-894c-015fd694a09d" />
</div>



## 🚀 部署方式

### 1. Docker部署

```shell
docker run -d -p 16181:16181 --name ymicp yiminger/ymicp
```

### 2. 本地部署（可执行文件）

- [📥 Release下载可执行文件](https://github.com/HG-ha/ICP_Query/releases)

### 3. 源码部署

```shell
git clone https://github.com/HG-ha/ICP_Query.git
cd ICP_Query
uv init
uv venv --python 3.11
uv pip install -r requirements.txt
```

## 💻 使用方法

### 使用查询模块

```python
import asyncio
from ymicp import beian

async def main(name):
    icp = beian()
    query = await icp.ymApp(name)
    print(query)

asyncio.run(main("微信"))
```

### 🔍使用icpApi查询接口

#### 支持八种类型查询：

| 类型 | 说明 |
|------|------|
| `web` | 网站 |
| `app` | APP |
| `mapp` | 小程序 |
| `kapp` | 快应用 |
| `bweb` | 违法违规网站 |
| `bapp` | 违法违规APP |
| `bmapp` | 违法违规小程序 |
| `bkapp` | 违法违规快应用 |

#### 示例请求

##### GET请求

- **URL格式**: `http://0.0.0.0:16181/query/{type}?search={name}`
  
- **示例1**: 查询域名 `baidu.com` 备案信息
  ```
  curl http://127.0.0.1:16181/query/web?search=baidu.com
  ```

- **示例2**: 根据网站的备案号 `京ICP证030173号` 查询备案信息
  ```
  curl http://127.0.0.1:16181/query/web?search=京ICP证030173号
  ```

- **示例3**: 根据企业名称查询备案信息
  ```
  curl http://127.0.0.1:16181/query/web?search=深圳市腾讯计算机系统有限公司
  ```

- **示例4**: 根据企业名称查询备案信息，每页20条数据，查询第3页
  ```
  curl http://127.0.0.1:16181/query/web?search=深圳市腾讯计算机系统有限公司&pageNum=3&pageSize=20
  ```

## 📊 响应参数说明

| 参数 | 说明 |
|------|------|
| lastPage | 据查询数量有多少页 |
| pages | 据查询数量有多少页 |
| pageSize | 每页几条数据 |
| pageNum | 第几页 |
| nextPage | 下一页的页面序号 |
| total | 据查询数量有多少页 |
| domain | 备案的域名 |
| domainId | 域名id |
| limitAccess | 是否限制接入 |
| mainLicence | ICP备案主体许可证号 |
| natureName | 主办单位性质 |
| serviceLicence | ICP备案服务许可证号 |
| unitName | 主办单位名称 |
| updateRecordTime | 审核通过日期 |
| contentTypeName | 服务前置审批项 |
| cityId | 城市ID |
| countyId | 区县ID |
| contentTypeName | 内容类型 |
| mainUnitAddress | 主体地址 |
| serviceName | 服务名称(APP、小程序或快应用名称) |
| version | 服务版本 |
| blackListLevel | 威胁等级，表示是否为违法违规应用，目前获得的等级为2时，表示暂无违法违规信息 |

## 🔗 其他资源

- [🔍 镜芯API](https://api2.wer.plus/)
- [☁️ 林枫云_站长首选云服务器](https://www.dkdun.cn/)
- [🌐 在线查询ICP备案](https://icp.show)

## ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=HG-ha/ICP_Query&type=Date)](https://star-history.com/#HG-ha/ICP_Query&Date)
