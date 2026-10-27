FROM python:3.14-slim AS builder

# No compiler toolchain here on purpose: every runtime dependency (python-can,
# ruyaml, paho-mqtt and their transitive deps) ships a pure-Python
# py3-none-any wheel, so nothing is built from source. Installing
# build-essential cost ~60s per emulated platform in CI for no benefit.

COPY requirements.txt .

RUN pip install --user --no-cache-dir -r requirements.txt

WORKDIR /app
COPY readme.md setup.py /app/
COPY rvc2mqtt /app/rvc2mqtt
RUN pip install --user --no-cache-dir .

FROM python:3.14-slim

RUN adduser worker
RUN install -o worker -g worker -d /config /floorplan /logs

COPY --chown=worker:worker --from=builder /root/.local /home/worker/.local

VOLUME ["/config", "/floorplan", "/logs"]
ENV PATH="/home/worker/.local/bin:${PATH}"

USER worker
WORKDIR /home/worker

CMD ["python3", "-m", "rvc2mqtt.app"]
