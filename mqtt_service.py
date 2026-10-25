"""Headless Eaton USB to MQTT service. Configuration comes from environment."""

import json
import logging
import os
import signal
import threading

from linux_reader import Reader
from mqtt_bridge import event_from_report, load_devices

LOG = logging.getLogger(__name__)


def main():
    import paho.mqtt.client as mqtt

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    host = os.environ.get("MQTT_HOST", "192.168.99.95").strip()
    port = int(os.environ.get("MQTT_PORT", "1883"))
    if not host or not 1 <= port <= 65535:
        raise ValueError("MQTT_HOST and MQTT_PORT must specify a valid broker")
    devices = load_devices(os.environ.get("DEVICES_FILE", "smarthome_devices.csv"))
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect_timeout = 10
    client.max_queued_messages_set(100)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    username = os.environ.get("MQTT_USERNAME", "")
    password = os.environ.get("MQTT_PASSWORD", "")
    if password and not username:
        raise ValueError("MQTT_USERNAME is required when a password is configured")
    if username:
        client.username_pw_set(username, password)

    def connected(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            LOG.error("MQTT connection rejected (check broker access settings)")
        else:
            LOG.info("MQTT connected")

    client.on_connect = connected
    client.connect_async(host, port, keepalive=30)
    client.loop_start()
    reader = None
    try:
        while not stop.is_set():
            if not client.is_connected():
                stop.wait(0.5)
                continue
            try:
                if reader is None:
                    reader = Reader(os.environ.get("USB_DEVICE", "/dev/eaton"))
                    reader.enable_reception()
                    LOG.info("USB reception enabled")
                event = event_from_report(reader.read(), devices)
                if event is None:
                    continue
                result = client.publish(
                    f"eaton/eaton_usb/{event['sender_id']}",
                    json.dumps(event, ensure_ascii=False), qos=1, retain=False,
                )
                if result.rc not in (mqtt.MQTT_ERR_SUCCESS, mqtt.MQTT_ERR_NO_CONN):
                    raise RuntimeError("MQTT publish queue rejected an event")
                # Bound shutdown latency while preserving ordered QoS 1 delivery.
                while not stop.is_set() and not result.is_published():
                    stop.wait(0.1)
                if not result.is_published():
                    LOG.warning("Stopping with an unacknowledged MQTT event")
            except OSError as exc:
                LOG.error("USB unavailable (%s); retrying in five seconds",
                          exc.strerror or type(exc).__name__)
                if reader is not None:
                    reader.close()
                    reader = None
                stop.wait(5)
    finally:
        if reader is not None:
            reader.close()
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
