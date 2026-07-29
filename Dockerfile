FROM python:3-alpine

RUN apk add --no-cache \
        wireless-tools iproute2 \
        libffi-dev rust python3-dev build-base

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt \
    && rm requirements.txt

COPY crawler/ crawler/
RUN mkdir -p /app/data

ENV PYTHONPATH=/app

VOLUME /app/data
WORKDIR /app/data

CMD ["python3", "-m", "crawler.main"]
