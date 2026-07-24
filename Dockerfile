FROM debian:trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        wireless-tools \
        iproute2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN grep -vE '^[[:space:]]*pytest' requirements.txt \
    | pip3 install --no-cache-dir --break-system-packages -r /dev/stdin \
    && rm requirements.txt

COPY crawler/ crawler/

RUN useradd -r -u 1000 -d /app/data -s /usr/sbin/nologin dashcam-crawler \
    && mkdir -p /app/data \
    && chown dashcam-crawler:dashcam-crawler /app/data

ENV PYTHONPATH=/app

WORKDIR /app/data

USER dashcam-crawler

CMD ["python3", "-m", "crawler.main"]
