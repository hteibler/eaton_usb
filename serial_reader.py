"""Serial transport for the Eaton CRSZ-00/01 (FT232 UART)."""

import threading

from debug_log import traffic
from protocol import build_switch_command


BAUD_RATE = 115200
MAX_FRAME_LENGTH = 255


class Reader:
    def __init__(self, port):
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("Serial transport requires pyserial; rebuild the container") from exc
        self.port = port
        self.connection = serial.Serial(port, BAUD_RATE, bytesize=8, parity="N",
                                        stopbits=1, timeout=0.25, write_timeout=3)
        self.buffer = bytearray()
        self.write_lock = threading.RLock()
        self.sequence = 0x11

    def enable_reception(self):
        # CRSZ-00/01 answers this identification probe before monitor startup.
        self.write(bytes.fromhex("5a 04 0b a5"))
        self.write(bytes.fromhex("5a 05 1a 01 a5"))

    def write(self, packet):
        with self.write_lock:
            if not self.connection.is_open:
                raise OSError("Serial device is closed")
            count = self.connection.write(packet)
            traffic("SERIAL TX", packet, written=count)
            if count != len(packet):
                raise OSError("Incomplete serial write; actuator state unknown")

    def send_switch(self, serial, command):
        with self.write_lock:
            packet = build_switch_command(serial, command, self.sequence)
            self.write(packet)
            self.sequence = 0x10 | ((self.sequence + 1) & 0x0F)
            return packet

    def read(self):
        """Extract one length-prefixed 5A...A5 frame from a byte stream."""
        while self.connection.is_open:
            while self.buffer:
                start = self.buffer.find(0x5A)
                if start < 0:
                    self.buffer.clear()
                    break
                if start:
                    del self.buffer[:start]
                if len(self.buffer) < 2:
                    break
                length = self.buffer[1]
                if not 4 <= length <= MAX_FRAME_LENGTH:
                    del self.buffer[0]
                    continue
                if len(self.buffer) < length:
                    break
                if self.buffer[length - 1] != 0xA5:
                    del self.buffer[0]
                    continue
                frame = bytes(self.buffer[:length])
                del self.buffer[:length]
                return frame
            data = self.connection.read(256)
            if not data:
                return b""
            traffic("SERIAL RX", data)
            self.buffer.extend(data)
        return b""

    def close(self):
        if self.connection.is_open:
            self.connection.close()
