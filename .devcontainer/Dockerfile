FROM debian:trixie

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    python3 python3-pip python3-venv \
    wireless-tools \
    iproute2 \
    curl git bash ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
