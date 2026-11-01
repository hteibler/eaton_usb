FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && mkdir /app/logs \
    && chown 10001:10001 /app/logs \
    && groupadd --gid 10001 bridge \
    && useradd --uid 10001 --gid bridge --no-create-home bridge
COPY debug_log.py protocol.py linux_reader.py serial_reader.py mqtt_bridge.py mqtt_service.py ./
USER bridge
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
CMD ["python", "mqtt_service.py"]
