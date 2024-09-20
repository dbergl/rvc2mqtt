FROM python:3.12-slim-bookworm

RUN pip install --upgrade pip
RUN adduser worker
RUN mkdir /home/worker/logs

USER worker

WORKDIR /home/worker

COPY --chown=worker:worker readme.md ./
COPY --chown=worker:worker setup.py ./
COPY --chown=worker:worker requirements.txt ./
RUN pip install --user --no-cache-dir -r requirements.txt
COPY --chown=worker:worker rvc2mqtt ./rvc2mqtt
RUN pip install --user --no-cache-dir .

ENV PATH="/home/worker/.local/bin:${PATH}"

CMD ["python3", "-m", "rvc2mqtt.app"]
