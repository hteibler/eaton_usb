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
    if sender_type == "Taster 2-fach" and action != "N/A":
        button = {0: "LEFT", 1: "RIGHT"}.get(report[9], "N/A")
    if (sender_type in ("Taster 4-fach", "CTAA-04/04")
            and action != "N/A" and report[9] < 4):
        button = str(report[9] + 1)
    if sender_type == "Fernbedienung" and action != "N/A" and report[9] < 12:
        channel = report[9] // 2 + 1
        side = "LEFT" if report[9] % 2 == 0 else "RIGHT"
        button = f"{channel}-{side}"
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
        "power_supply": {
            "netzversorgt": "MAINS_POWERED",
            "voll": "BATTERY_FULL",
            "fast voll": "BATTERY_NEARLY_FULL",
        }.get(telegram.battery, telegram.battery.replace("Code ", "CODE ") or "N/A"),
        "reception_percent": telegram.quality,
        "rssi_dbm": telegram.rssi_dbm,
        "raw": telegram.raw,
        "other": other,
    }
