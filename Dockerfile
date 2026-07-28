FROM python:3-alpine

RUN apk add --no-cache libffi-dev gcc musl-dev wireless-tools iproute2

WORKDIR /app

COPY requirements.txt .
# --break-system-packages is appropriate here: this is a container image where
# there is no system Python to protect, and using pip directly is simpler than
# adding a venv layer.
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt \
    && rm requirements.txt

COPY crawler/ crawler/
RUN mkdir -p /app/data

ENV PYTHONPATH=/app

VOLUME /app/data
WORKDIR /app/data

CMD ["python3", "-m", "crawler.main"]
