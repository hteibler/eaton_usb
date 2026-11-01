"""Linux hidraw transport for the Eaton CKOZ-00/13 (188a:1102)."""

import fcntl
import os
import select
import struct

from debug_log import traffic
from protocol import build_switch_command


class Reader:
    def __init__(self, path):
        self.sequence = 0x11
        self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        try:
            info = bytearray(8)
            fcntl.ioctl(self.fd, 0x80084803, info)  # HIDIOCGRAWINFO
            bus, vendor, product = struct.unpack("IHH", info)
            if (bus, vendor, product) != (3, 0x188A, 0x1102):
                raise RuntimeError("Selected device is not an Eaton USB 188a:1102")
        except BaseException:
            self.close()
            raise

    def enable_reception(self):
        # The observed stick descriptor defines 62-byte, unnumbered reports.
        # hidraw writes require a leading zero report ID; reads omit it.
        report = b"\x00" + bytes.fromhex("5a 05 1a 01 a5").ljust(62, b"\x00")
        count = os.write(self.fd, report)
        traffic("HID TX", report, written=count)
        if count != len(report):
            raise OSError("Incomplete USB reception command")

    def send_switch(self, serial, command):
        packet = build_switch_command(serial, command, self.sequence)
        report = b"\x00" + packet.ljust(62, b"\x00")
        count = os.write(self.fd, report)
        traffic("HID TX", report, written=count)
        if count != len(report):
            raise OSError("Incomplete USB switch command; actuator state unknown")
        self.sequence = 0x10 | ((self.sequence + 1) & 0x0F)
        return packet

    def read(self):
        if not select.select([self.fd], [], [], 0.5)[0]:
            return b""
        report = os.read(self.fd, 62)
        if not report:
            raise OSError("USB device disconnected")
        traffic("HID RX", report)
        return report

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
