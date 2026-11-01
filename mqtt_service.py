"""Headless Eaton USB to MQTT service. Configuration comes from environment."""

import json
import logging
import os
import queue
import signal
import threading
import time

from debug_log import configure_debug, traffic
from linux_reader import Reader
from mqtt_bridge import event_from_report, load_devices

LOG = logging.getLogger(__name__)


COMMAND_TOPIC = "eaton/eaton_usb_do"


def parse_command(payload):
    if len(payload) > 1024:
        raise ValueError("Command payload is too large")
    try:
        data = json.loads(payload)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Command must be valid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("Command must be a JSON object")
    serial = data.get("receiver_id")
    if isinstance(serial, str) and serial.isascii() and serial.isdecimal():
        serial = int(serial)
    if type(serial) is not int or not 1 <= serial <= 0xFFFFFFFF:
        raise ValueError("receiver_id must be an integer or decimal string between 1 and 4294967295")
    command = data.get("command")
    if command not in ("on", "off"):
        raise ValueError("Only on/off are supported; other commands need captures")
    return serial, command.upper()


def receive_command(message, commands, ready):
    traffic("MQTT RX", message.payload, topic=message.topic, retain=message.retain)
    if message.topic != COMMAND_TOPIC:
        return
    if message.retain:
        LOG.warning("Retained command rejected")
        return
    try:
        command = parse_command(message.payload)
        if not ready.is_set():
            LOG.warning("Command rejected: USB unavailable")
            return
        commands.put_nowait(command)
    except (ValueError, queue.Full) as exc:
        LOG.warning("Command rejected: %s", exc or "command queue full")


class ConfirmationWait:
    """Track one command using observed ACK addresses, without automatic retries."""

    def __init__(self):
        self.pending = None

    def start(self, packet, command, now):
        sender = int.from_bytes(packet[10:14], "little")
        receiver = int.from_bytes(packet[15:19], "little")
        self.pending = (receiver, sender, command, now + 3.0)
        LOG.info("%s command written to radio; receiver_id=%d; waiting for acknowledgement",
                 command, receiver)

    def expire(self, now):
        if self.pending is not None and now >= self.pending[3]:
            self.cancel("no matching acknowledgement within three seconds")

    def observe(self, event, now):
        self.expire(now)
        if self.pending is None:
            return
        receiver, sender, command, _ = self.pending
        if (event["other"].get("message") == "ACKNOWLEDGEMENT"
                and event["sender_id"] == receiver and event["receiver_id"] == sender):
            LOG.info("Radio acknowledgement received; receiver_id=%d; command=%s; "
                     "physical actuator state unverified", receiver, command)
            self.pending = None

    def cancel(self, reason):
        if self.pending is not None:
            receiver, _, command, _ = self.pending
            LOG.warning("Command confirmation unavailable; receiver_id=%d; command=%s; %s; "
                        "actuator state unconfirmed", receiver, command, reason)
            self.pending = None


def reader_class(transport):
    if transport == "hid":
        return Reader
    if transport == "serial":
        from serial_reader import Reader as SerialReader
        return SerialReader
    raise ValueError("EATON_TRANSPORT must be hid or serial")


def main():
    import paho.mqtt.client as mqtt

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(levelname)s: %(message)s",
                        datefmt="%H:%M:%S")
    configure_debug(os.environ.get("DEBUG", "false"),
                    os.environ.get("DEBUG_LOG", "debug.log"))
    transport = os.environ.get("EATON_TRANSPORT", "hid")
    transport_reader = reader_class(transport)
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

    commands = queue.Queue(maxsize=20)
    ready = threading.Event()

    def connected(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            LOG.error("MQTT connection rejected (check broker access settings)")
        else:
            result, _ = client.subscribe(COMMAND_TOPIC, qos=0)
            if result != mqtt.MQTT_ERR_SUCCESS:
                LOG.error("MQTT command subscription failed")
            LOG.info("MQTT connected")

    client.on_message = lambda client, userdata, message: receive_command(message, commands, ready)
    client.on_connect = connected
    client.connect_async(host, port, keepalive=30)
    client.loop_start()
    reader = None
    confirmation = ConfirmationWait()
    try:
        while not stop.is_set():
            confirmation.expire(time.monotonic())
            if not client.is_connected():
                confirmation.cancel("MQTT disconnected")
                ready.clear()
                while True:
                    try:
                        commands.get_nowait()
                    except queue.Empty:
                        break
                stop.wait(0.5)
                continue
            operation = "opening USB device"
            try:
                if reader is None:
                    reader = transport_reader(os.environ.get("USB_DEVICE", "/dev/eaton"))
                    operation = "enabling USB reception"
                    reader.enable_reception()
                    LOG.info("USB reception enabled (%s transport)", transport)
                ready.set()
                if confirmation.pending is None:
                    try:
                        serial, command = commands.get_nowait()
                    except queue.Empty:
                        pass
                    else:
                        operation = f"sending {command} to receiver_id={serial}"
                        packet = reader.send_switch(serial, command)
                        confirmation.start(packet, command, time.monotonic())
                operation = "reading USB report"
                report = reader.read()
                confirmation.expire(time.monotonic())
                event = event_from_report(report, devices)
                if event is None:
                    if report:
                        offset = 1 if len(report) > 1 and report[0] != 0x5A and report[1] == 0x5A else 0
                        packet = report[offset:]
                        if (len(packet) >= 4 and packet[0] == 0x5A
                                and 4 <= packet[1] <= len(packet)
                                and packet[packet[1] - 1] == 0xA5):
                            LOG.info("USB reply: type=0x%02X, length=%d (not a radio event)",
                                     packet[2], packet[1])
                        else:
                            LOG.warning("Unrecognized USB report: length=%d", len(report))
                    continue
                confirmation.observe(event, time.monotonic())
                topic = f"eaton/eaton_usb/{event['sender_id']}"
                payload = json.dumps(event, ensure_ascii=False)
                result = client.publish(topic, payload, qos=1, retain=True)
                traffic("MQTT TX", payload, topic=topic, qos=1, retain=True,
                        result=result.rc)
                if result.rc not in (mqtt.MQTT_ERR_SUCCESS, mqtt.MQTT_ERR_NO_CONN):
                    raise RuntimeError("MQTT publish queue rejected an event")
                # Bound shutdown latency while preserving ordered QoS 1 delivery.
                while not stop.is_set() and not result.is_published():
                    stop.wait(0.1)
                if not result.is_published():
                    LOG.warning("Stopping with an unacknowledged MQTT event")
            except OSError as exc:
                confirmation.cancel("radio connection failed")
                LOG.error("USB unavailable while %s (%s, errno=%s); retrying in five seconds",
                          operation, exc.strerror or str(exc) or type(exc).__name__, exc.errno)
                ready.clear()
                while True:
                    try:
                        commands.get_nowait()
                    except queue.Empty:
                        break
                if reader is not None:
                    reader.close()
                    reader = None
                stop.wait(5)
    finally:
        confirmation.cancel("service stopping")
        ready.clear()
        if reader is not None:
            reader.close()
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
