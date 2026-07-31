FROM python:3.12-slim
WORKDIR /app
COPY packages/core /app/packages/core
COPY apps/api /app/apps/api
RUN pip install --no-cache-dir /app/packages/core[api,telegram]
ENV PYTHONPATH=/app/packages/core
EXPOSE 8000
CMD ["uvicorn", "main:app", "--app-dir", "/app/apps/api", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
