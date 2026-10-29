# Public Gongmudam demo for Cloudflare Containers. Build from the staging
# directory written by tools/stage_container.py, never from a private DB.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1 TZ=Asia/Seoul
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY integration integration
COPY desktop desktop
COPY service-template service-template
COPY start.py start.py
EXPOSE 8080
CMD ["python", "/app/start.py"]
