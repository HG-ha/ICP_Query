#### 欢迎注册镜芯API [api2.wer.plus](https://api2.wer.plus) 稳定、高效的API服务

#### 在线测试ICP备案接口 [ICP备案查询](https://www.icp.show)

#### 项目仅限于学习交流逆向与验证码识别技术使用
### 关于本项目
1. ICP备案查询，基于Python，全异步构建的高性能ICP查询模块，支持分页查询
2. 直接从工业和信息化部政务服务平台抓取实时数据，支持Web、APP、小程序、快应用名称查询
3. 支持根据备案号查询，支持根据企业名称查询，支持违法违规域名、APP查询
4. 提供简单易用的高性能接口以及发行版程序
5. 禁止售卖本项目，禁止用于违法目的，开源目的仅用于学习交流验证码识别和js逆向技术

### 部署

#### 20250901版本
- 添加独立配置文件，支持配置多种代理方式，内置webui，更新最新的查询接口，适当优化模型性能，优化内部错误处理
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

#### 20240225版本（yolo8+未转化孪生神经网络，非生产环境），性能提升，支持替换模型，数据集是手动生成的，存在误差。权重文件可以二次训练，欢迎贡献更好的模型，或者提供更真实、全面的数据集来优化模型。该发布方式不适用于生产环境。
1. docker部署（确保磁盘预留有3G空间），在1核CPU、1G内存的情况下，能够运行至少2个容器
   ``` shell
   # 拉取镜像
   docker pull yiminger/ymicp:yolo8_latest
   # 运行并转发容器16181端口到本地所有地址
   docker run -d -p 16181:16181 yiminger/ymicp:yolo8_latest
   ```
2. 手动部署
   ```
   # 先自行安装Python3.8+
   # 下载环境
   https://wwf.lanzn.com/iddrE1pc370j
   # 解压
   unzip icpApi_20240225_yolo8.zip && cd icpApi_20240225_yolo8
   # 安装torch-cpu
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
   # 安装依赖
   pip install -r requirements.txt -i https://mirror.baidu.com/pypi/simple
   # 运行
   python icpApi.py
   ```

#### 2. 自动打码，20231209版本（paddle），基本上可以进行自动打码，支持替换模型
1. docker部署（确保磁盘预留有3G空间）
   ``` shell
   # 拉取镜像
   docker pull yiminger/ymicp:latest
   # 运行并转发容器16181端口到本地所有地址
   docker run -d -p 16181:16181 yiminger/ymicp:latest
   ```
2. 手动部署
   ```
   # 先自行安装Python3.8+
   # 下载环境
   wget https://github.com/HG-ha/ICP_Query/raw/main/2023-12-9_auto_icp-Api.zip
   # 解压
   unzip 2023-12-9_auto_icp-Api.zip && cd icp_Api
   # 安装依赖
   pip install -r requirements.txt -i https://mirror.baidu.com/pypi/simple
   # 运行
   python icpApi.py
   
   # 实测在该配置 Linux Centos7.2  1(cpu)  1G(RAM) 上至少可以同时运行3个进程(不同端口)
   ```
3. 在Android手机上部署（非docker）,测试机型为meizu 16S Pro，性能发挥正常
   1. [下载Termux](https://github.com/termux/termux-app/releases)，本人测试使用版本为0.118
   2. 更新环境，更新比较慢的可以去搜索如何替换国内源
      ```
      pkg update && pkg upgrade -y
      ```
   3. 安装proot-distro
      ```
      pkg install proot-distro -y
      ```
   4. 安装并登录ubuntu
      ```
      proot-distro install ubuntu
      proot-distro login ubuntu
      ```
   5. 安装系统环境依赖
      ```
      apt update
      apt-get install wget zlib1g-dev libbz2-dev libssl-dev libncurses5-dev libsqlite3-dev libreadline-dev tk-dev libgdbm-dev libdb-dev libpcap-dev xz-utils libexpat1-dev liblzma-dev libffi-dev libc6-dev build-essential libgl1 libglib2.0-dev -y
      ```
   6. 编译安装python
      ```
      wget https://mirrors.huaweicloud.com/python/3.8.18/Python-3.8.18.tgz
      tar zxfv Python-3.8.18.tgz
      cd Python-3.8.18
      ./configure && make && make install
      ```
   7. 下载部署源码包
      ```
      wget https://github.com/HG-ha/ICP_Query/raw/main/2023-12-9_auto_icp-Api.zip
      unzip 2023-12-9_auto_icp-Api.zip
      cd icp_Api
      pip3 install -r requirements.txt -i https://mirror.baidu.com/pypi/simple
      ```
   8. 启动
      ```
      python3 icpApi.py
      ```
4. 在线体验接口
   [ICP备案查询](https://hg-ha.github.io/icpb/)

#### （手动打码）20231130修复版本，只提供手动点选验证码，可接入其他打码平台或自行实现，修改ymicp.py，按照small_selice方法返回对应参数即可
1. 下载icpApi.py和ymicp.py
2. 安装requirements.txt中的依赖即可

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
[API文档](https://api2.wer.plus/doc/14)

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


## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=HG-ha/ICP_Query&type=Date)](https://star-history.com/#HG-ha/ICP_Query&Date)
