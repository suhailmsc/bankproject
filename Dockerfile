FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 10001 app
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
# Build-time only key so collectstatic can import settings; the real key comes from the environment at runtime.
RUN SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(64))')" DEBUG=0 \
    python manage.py collectstatic --noinput \
 && chmod +x docker-entrypoint.sh \
 && chown -R app:app /app

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"
ENTRYPOINT ["./docker-entrypoint.sh"]
