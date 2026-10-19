FROM python:3.13-slim
ENV STAFF_PIN=steveadmin BARBER_PIN_DAVID=stevedavid BARBER_PIN_STEVE=stevesteve BARBER_PIN_JOEY=stevejosey BARBER_PIN_MIKE=stevemike PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATABASE_PATH=/app/data/barber.sqlite PUBLIC_ORIGIN=https://stevesbarbershopny.com
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 1000 appuser
# Allow the unprivileged app user to bind port 83 on container runtimes
# that reserve ports below 1024.
RUN apt-get update && apt-get install -y --no-install-recommends libcap2-bin \
    && setcap 'cap_net_bind_service=+ep' "$(readlink -f /usr/local/bin/python3)" \
    && rm -rf /var/lib/apt/lists/*
COPY --chown=appuser:appuser app ./app
COPY --chown=appuser:appuser drizzle ./drizzle
RUN mkdir -p /app/data && chown appuser:appuser /app/data
USER appuser
EXPOSE 83
VOLUME ["/app/data"]
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:83/api/health',timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "83", "--proxy-headers"]
