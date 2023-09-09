# ICP_Query
ICP备案查询，基于Python3.8，全异步构建的高性能ICP查询模块，直接从工业和信息化部政务服务平台抓取实时数据，支持Web、APP、小程序、快应用查询，支持根据备案号查询，同时提供简单易用的高性能Api


### 安装依赖
``` shell
# 可以使用低版本包，基本都包含需要的模块
pip install -r requirements.txt
```

### 使用
``` python
import asyncio
from ymicp import beian

async def main(name):
    icp = beian()
    query = await icp.ymApp(name)
    print(query)

asyncio.run(main("微信"))
```

### 使用icpApi
#### 查询接口
##### 支持四种类型查询：
- 网站： web
- APP: app
- 小程序: mapp
- 快应用: kapp
#### Request
- Method: **GET** **POST**
- URL:  ```/query/{type}?search={name}```
```
```
##### Linux运行
1. 源代码运行
``` shell
python3 icpApi.py
```
2. 独立程序运行
``` shell
./icpApi.bin
```
##### Windows
1. 双击运行即可
### 请喝茶吗

| 支付宝                                                                                     | 微信                                                                                    | 群                |
| --------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ---------------- |
| <img src="https://github.com/HG-ha/qinglong/blob/main/zfb.jpg?raw=true" title="" alt="zfb" width="120px" height="120px"> | <img title="" src="https://github.com/HG-ha/qinglong/blob/main/wx.png?raw=true" alt="wx" width="120px" height="120px"> | 一铭API：1029212047 |
|                                                                                       |                                                                                       | 镜芯科技：376957298   |



### 其他项目

[一铭API](https://api.wer.plus)
