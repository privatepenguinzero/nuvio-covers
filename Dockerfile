FROM python:3.13-slim

ARG MONTSERRAT_REF=v7.222
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates tzdata \
 && mkdir -p /app/fonts \
 && for w in Black ExtraBold Bold; do \
      curl -fsSL -o /app/fonts/Montserrat-$w.ttf \
        "https://raw.githubusercontent.com/JulietaUla/Montserrat/${MONTSERRAT_REF}/fonts/ttf/Montserrat-$w.ttf"; \
    done \
 && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ /app/
COPY config.json /app/config.json

RUN useradd -r -u 10001 covers && mkdir -p /data/covers && chown -R covers /data
USER covers
VOLUME /data
EXPOSE 8080
ENV PYTHONUNBUFFERED=1 TZ=Europe/Rome
HEALTHCHECK --interval=60s --timeout=5s --start-period=60s CMD python -c "import urllib.request,sys;urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=4)" || exit 1
CMD ["python", "/app/main.py"]
