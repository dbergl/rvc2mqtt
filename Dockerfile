FROM python:3.12-bookworm AS builder

ARG TARGETPLATFORM

COPY requirements.txt .

RUN  apt-get update && apt-get install build-essential -y

RUN pip install --upgrade pip

RUN if [ "${TARGETPLATFORM}" = "linux/arm/v7" ]; then \
  MSGPACK_PUREPYTHON=1 pip install --user --no-cache-dir -r requirements.txt; \
  else \
  pip install --user --no-cache-dir -r requirements.txt; \
  fi
WORKDIR /app
COPY readme.md .
COPY setup.py .
COPY rvc2mqtt .
RUN pip install --user --no-cache-dir .

FROM python:3.12-slim-bookworm

RUN adduser worker
COPY --chown=worker:worker --from=builder /root/.local /home/worker/.local
COPY --chown=worker:worker --from=builder /app /home/worker/rvc2mqtt
USER worker
WORKDIR /home/worker

RUN mkdir logs floorplan config

ENV PATH="/home/worker/.local/bin:${PATH}"

CMD ["python3", "-m", "rvc2mqtt.app"]
