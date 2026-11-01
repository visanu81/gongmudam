# Public Gongmudam demo for Cloudflare Containers. Build from the staging
# directory written by tools/stage_container.py, never from a private DB.

# kordoc reads PDFs in 업무자료 정리 (Node.js 20+). Only the PDF part is installed;
# the OCR and image add-ons are optional dependencies and are left out.
FROM node:22-bookworm-slim AS kordoc
WORKDIR /opt/kordoc
RUN echo '{"name":"gongmudam-kordoc","private":true}' > package.json \
 && npm install --omit=optional --no-audit --no-fund --ignore-scripts kordoc@4.24.33 pdfjs-dist@4.10.38

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONUTF8=1 TZ=Asia/Seoul \
    GONGMUDAM_NODE=/usr/local/bin/node GONGMUDAM_KORDOC_CLI=/opt/kordoc/node_modules/kordoc/dist/cli.js
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 && rm -rf /var/lib/apt/lists/*
COPY --from=kordoc /usr/local/bin/node /usr/local/bin/node
COPY --from=kordoc /opt/kordoc /opt/kordoc
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY integration integration
COPY desktop desktop
COPY service-template service-template
COPY start.py start.py
EXPOSE 8080
CMD ["python", "/app/start.py"]
