FROM python:3.11-slim

WORKDIR /icp_Api

COPY . /icp_Api/

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 16181

CMD ["python3", "icpApi.py"]
