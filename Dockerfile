# 基于的基础镜像
FROM python:3.8.7

# 复制当前文件到容器中的 /icp_Api 目录
COPY ./* /icp_Api/

# 确保 /icp_Api 是目录
RUN mkdir -p /icp_Api

# 设置工作目录
WORKDIR /icp_Api

# 更新 apt 源并安装依赖
RUN echo 'deb https://mirrors.tuna.tsinghua.edu.cn/debian/ buster main non-free contrib' > /etc/apt/sources.list \
    && echo 'deb-src https://mirrors.tuna.tsinghua.edu.cn/debian/ buster main non-free contrib' >> /etc/apt/sources.list \
    && echo 'deb https://mirrors.tuna.tsinghua.edu.cn/debian-security buster/updates main' >> /etc/apt/sources.list \
    && echo 'deb-src https://mirrors.tuna.tsinghua.edu.cn/debian-security buster/updates main' >> /etc/apt/sources.list \
    && echo 'deb https://mirrors.tuna.tsinghua.edu.cn/debian/ buster-updates main non-free contrib' >> /etc/apt/sources.list \
    && echo 'deb-src https://mirrors.tuna.tsinghua.edu.cn/debian/ buster-updates main non-free contrib' >> /etc/apt/sources.list \
    && apt-get update -y \
    && apt-get install -y libgl1 \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
RUN pip install -r /icp_Api/requirements.txt -i https://mirrors.aliyun.com/pypi/simple

# 暴露端口
EXPOSE 16181

# 启动应用
CMD ["python3", "/icp_Api/icpApi.py"]
