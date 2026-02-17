FROM python:3.12-slim-bookworm AS builder

RUN  apt-get update && apt-get install build-essential -y

RUN pip install --upgrade pip

COPY requirements.txt .

ARG MSGPACK_PUREPYTHON=1 

RUN pip install --user --no-cache-dir -r requirements.txt

WORKDIR /app
COPY readme.md /app
COPY setup.py /app
COPY rvc2mqtt /app/rvc2mqtt
RUN pip install --user --no-cache-dir .

FROM python:3.12-slim-bookworm

RUN adduser worker
RUN install -o worker -g worker -d /config /floorplan /logs

COPY --chown=worker:worker --from=builder /root/.local /home/worker/.local

VOLUME ["/config", "/floorplan", "/logs"]
ENV PATH="/home/worker/.local/bin:${PATH}"

USER worker
WORKDIR /home/worker

CMD ["python3", "-m", "rvc2mqtt.app"]
