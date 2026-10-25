"""Translate validated radio reports into the MQTT event contract."""

import csv
from pathlib import Path

from protocol import decode


def load_devices(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as source:
        devices = {}
        for row in csv.DictReader(source):
            serial = (row.get("Seriennummer") or "").strip()
            if serial.isdecimal():
                devices[int(serial)] = (
                    (row.get("Gerätename") or "").strip(),
                    (row.get("Gerätetype") or "").strip(),
                )
        return devices


def event_from_report(report, devices):
    if len(report) > 1 and report[0] != 0x5A and report[1] == 0x5A:
        report = report[1:]
    if len(report) < 2:
        return None
    size = report[1]
    # Both IDs and the two RSSI bytes must precede the frame terminator.
    if (size < 22 or size > len(report) or report[0] != 0x5A
            or report[2] != 3 or report[size - 1] != 0xA5):
        return None
    telegram = decode(report)
    kind = report[3]
    action = {
        0x50: "ON", 0x51: "OFF", 0x54: "ON_PRESSED", 0x55: "ON_RELEASED",
        0x56: "OFF_PRESSED", 0x57: "OFF_RELEASED",
    }.get(kind, "N/A")
    sender_name, sender_type = devices.get(telegram.source, ("", ""))
    button = "N/A"
    # Apply DT1's observed side layout to the same two-button device class.
    if (telegram.source == 534129 or sender_type == "Taster 2-fach") and kind in (0x50, 0x51, 0x54, 0x55, 0x56, 0x57):
        button = {0: "LEFT", 1: "RIGHT"}.get(report[9], "N/A")
    other = {}
    if action == "N/A":
        other["message"] = {1: "ACKNOWLEDGEMENT", 0x70: "LEGACY STATUS"}.get(
            kind, f"UNKNOWN TYPE 0x{kind:02X}")
        other["raw"] = telegram.raw
    if kind in (0x50, 0x51, 0x54, 0x55, 0x56, 0x57) and report[7] == 0x10:
        other["repeat"] = True
    if telegram.destination_dp is not None:
        other["receiver_data_point"] = telegram.destination_dp
    receiver_name = devices.get(telegram.destination, ("", ""))[0]
    return {
        "sender_id": telegram.source,
        "sender_name": sender_name,
        "sender_type": sender_type,
        "receiver_id": telegram.destination,
        "receiver_name": receiver_name,
        "button": button,
        "action": action,
        "other": other,
    }
