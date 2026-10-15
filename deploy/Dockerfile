FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    DB_PATH=/data/imgrsz.sqlite STATS_PATH=/srv/www/stats.json GIGACHAT_CA_DIR=/app/certs
WORKDIR /app
COPY bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY deploy/certs/ /app/certs/
COPY bot/app/ /app/app/
CMD ["python", "-m", "app.main"]
