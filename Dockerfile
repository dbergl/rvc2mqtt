FROM python:3.12-bookworm AS builder

RUN  apt-get update && apt-get install build-essential -y

RUN pip install --upgrade pip

COPY requirements.txt .

ARG MSGPACK_PUREPYTHON=1 

RUN pip install --user --no-cache-dir -r requirements.txt

WORKDIR /app
COPY readme.md .
COPY setup.py .
COPY rvc2mqtt .
RUN pip install --user --no-cache-dir .

FROM python:3.12-slim-bookworm

RUN adduser worker
RUN install -o worker -g worker -d /config /floorplan /logs

COPY --chown=worker:worker --from=builder /root/.local /home/worker/.local
COPY --chown=worker:worker --from=builder /app /app

VOLUME ["/config", "/floorplan", "/logs"]
ENV PATH="/home/worker/.local/bin:${PATH}"

USER worker
WORKDIR /app

CMD ["python3", "-m", "rvc2mqtt.app"]
