FROM python:3.11-slim

WORKDIR /icp_Api

# Python 源码
COPY src/python/ /icp_Api/
# 共享资源（配置 / 前端）
COPY config.yml /icp_Api/config.yml
COPY templates/ /icp_Api/templates/
COPY static/ /icp_Api/static/

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 16181

CMD ["python3", "icpApi.py"]
