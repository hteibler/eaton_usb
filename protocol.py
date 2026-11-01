"""Read-only decoder for observed CKOZ-00/13 input reports.

The fields here were checked against a simultaneous MRF 2.78 monitor export.
Unknown message types and fields remain visible as hexadecimal data.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Telegram:
    source: Optional[int]
    destination: Optional[int]
    message: str
    battery: str
    quality: Optional[int]
    rssi_dbm: Optional[float]
    destination_dp: Optional[int]
    raw: str


MESSAGE_TYPES = {
    0x01: "BESTÄTIGUNG",
    0x50: "ON",
    0x51: "OFF",
    0x54: "ON PRESSED",
    0x55: "ON RELEASED",
    0x56: "OFF PRESSED",
    0x57: "OFF RELEASED",
    0x70: "STATUS alt",
}

BATTERY = {
    0x03: "fast voll",
    0x04: "voll",
}


def decode(report: bytes) -> Telegram:
    if len(report) > 1 and report[0] != 0x5A and report[1] == 0x5A:
        report = report[1:]  # Windows HID API can prepend a report ID.

    raw = report.hex(" ").upper()
    if len(report) < 4 or report[0] != 0x5A:
        return Telegram(None, None, "Unbekannter USB-Bericht", "", None, None, None, raw)

    size = report[1]
    if size < 7 or size > len(report) or report[size - 1] != 0xA5:
        return Telegram(None, None, "Ungültiger Telegrammrahmen", "", None, None, None, raw)

    packet = report[:size]
    kind = packet[3]
    source = int.from_bytes(packet[10:14], "little") if size >= 14 else None
    destination = int.from_bytes(packet[15:19], "little") if size >= 19 else None
    destination_dp = packet[14] if kind == 0x70 and size >= 19 else None
    message = MESSAGE_TYPES.get(kind, f"Typ 0x{kind:02X}")
    battery = "netzversorgt" if kind in (0x01, 0x70) else ""
    if kind in (0x50, 0x51, 0x54, 0x55, 0x56, 0x57) and size > 8:
        battery = BATTERY.get(packet[8], f"Code 0x{packet[8]:02X}")
        if size > 7 and packet[7] == 0x10:
            message += " (Wiederholung)"

    # The last two payload bytes encode RSSI in tenths of dBm, signed LE.
    # MRF maps -101 dBm to 0% and -51 dBm to 100%.
    rssi = int.from_bytes(packet[-3:-1], "little", signed=True) / 10
    quality = max(0, min(100, round((rssi + 101) * 2)))
    return Telegram(source, destination, message, battery, quality, rssi, destination_dp, packet.hex(" ").upper())


def build_switch_command(serial: int, command: str, sequence: int) -> bytes:
    """Build captured 0x1B frame; fixed fields verified for this installation only."""
    if type(serial) is not int or not 1 <= serial <= 0xFFFFFFFF:
        raise ValueError("Receiver ID must be an integer between 1 and 4294967295.")
    if command not in ("ON", "OFF"):
        raise ValueError("Only ON and OFF are supported.")
    if type(sequence) is not int or not 0x10 <= sequence <= 0x1F:
        raise ValueError("Switch sequence must be between 0x10 and 0x1F.")
    packet = bytearray.fromhex("5a 17 1b 50 00 13 00 82 07 00 80 00 00 00 00")
    packet[3] = 0x50 if command == "ON" else 0x51
    packet[6] = sequence
    packet.extend(serial.to_bytes(4, "little"))
    packet.append(0)
    # CRC-16/KERMIT over bytes 3..19, stored little-endian.
    crc = 0
    for value in packet[3:]:
        crc ^= value
        for _ in range(8):
            crc = (crc >> 1) ^ (0x8408 if crc & 1 else 0)
    packet.extend(crc.to_bytes(2, "little"))
    packet.append(0xA5)
    return bytes(packet)
