FROM python:3.13-slim
ENV STAFF_PIN=admin PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATABASE_PATH=/app/data/barber.sqlite PUBLIC_ORIGIN=https://stevesbarbershopny.com
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 1000 appuser
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser drizzle ./drizzle
RUN mkdir -p /app/data && chown appuser:appuser /app/data
USER appuser
EXPOSE 3000
VOLUME ["/app/data"]
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/api/health',timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3000", "--proxy-headers"]
