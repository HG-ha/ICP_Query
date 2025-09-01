# 基于的基础镜像
FROM python:3.11.13

# 设置工作目录
WORKDIR /icp_Api

# 复制所有文件到容器中的 /icp_Api 目录
COPY . /icp_Api/

# 更新 apt 源并安装依赖
RUN apt-get update -y \
    && apt-get install -y libgl1 \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
RUN pip install -r requirements.txt

# 暴露端口
EXPOSE 16181

# 启动应用
CMD ["python3", "icpApi.py"]