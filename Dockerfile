FROM alpine:3

RUN apk add --no-cache \
        wireless-tools iproute2 \
        python3 \
        py3-pip \
        py3-requests \
        py3-beautifulsoup4 \
        py3-paramiko \
        py3-pytest \
        ## --- google-cloud-storage dependencies
        py3-protobuf py3-proto-plus py3-invoke py3-asn1 py3-asn1-modules py3-google-api-core py3-googleapis-common-protos \
        ## --- google-cloud-storage dependencies
        ## --- build dependencies for crc32c
        build-base crc32c-dev

WORKDIR /app

COPY requirements.txt .
RUN python3 -m venv --system-site-packages .venv \
    && ./.venv/bin/python3 -m pip install --no-cache-dir --upgrade pip \
    && ./.venv/bin/pip3 install --no-cache-dir -r requirements.txt

COPY crawler/ crawler/
RUN mkdir -p /app/data

ENV PYTHONPATH=/app

VOLUME /app/data
WORKDIR /app/data

CMD ["/app/.venv/bin/python3", "-m", "crawler.main"]
