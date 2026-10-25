FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 bridge \
    && useradd --uid 10001 --gid bridge --no-create-home bridge
COPY protocol.py linux_reader.py mqtt_bridge.py mqtt_service.py ./
USER bridge
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
CMD ["python", "mqtt_service.py"]
