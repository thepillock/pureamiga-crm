FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    CRM_DATA_DIR=/data \
    PORT=3300 \
    PUID=99 \
    PGID=100 \
    TZ=Europe/London

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput

# Set by the GitHub Actions build: version (e.g. 1.2.0 or test-abc1234) and channel (stable/test).
# The test channel shows a TEST banner automatically.
ARG APP_VERSION=dev
ARG APP_CHANNEL=dev
ENV APP_VERSION=${APP_VERSION} \
    APP_CHANNEL=${APP_CHANNEL}
LABEL org.opencontainers.image.source="https://github.com/thepillock/pureamiga-crm" \
      org.opencontainers.image.version="${APP_VERSION}"

VOLUME /data
EXPOSE 3300
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s \
  CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','3300'))" || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["sh", "-c", "exec gunicorn crm.wsgi:application --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --worker-tmp-dir /tmp --access-logfile -"]
