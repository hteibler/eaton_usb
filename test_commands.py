import json
import queue
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from linux_reader import Reader
from mqtt_service import ConfirmationWait, COMMAND_TOPIC, parse_command, receive_command
from protocol import build_switch_command


class CommandTests(unittest.TestCase):
    def test_captured_frame_matches_reference(self):
        # Fixed vectors extracted from the supplied Windows reference.
        for command, checksum in (("ON", "b8 19"), ("OFF", "b7 09")):
            kind = "50" if command == "ON" else "51"
            expected = bytes.fromhex(
                f"5a 17 1b {kind} 00 13 11 82 07 00 80 00 00 00 00 "
                f"c8 01 00 00 00 {checksum} a5")
            self.assertEqual(build_switch_command(456, command, 0x11), expected)
        for serial in (1, 0xFFFFFFFF):
            packet = build_switch_command(serial, "ON", 0x10)
            self.assertEqual(packet[15:19], serial.to_bytes(4, "little"))
        for serial, command, sequence in ((True, "ON", 0x10), (0, "ON", 0x10),
                                          (456, "toggle", 0x10), (456, "ON", 0x20)):
            with self.assertRaises(ValueError):
                build_switch_command(serial, command, sequence)

    def test_command_validation(self):
        for command in ("on", "off"):
            self.assertEqual(parse_command(json.dumps({"receiver_id": 456, "command": command})),
                             (456, command.upper()))
        for payload in (b"", b"\xff", b"[]", b"null", b"{" , b"x" * 1025):
            with self.subTest(payload=payload[:20]), self.assertRaises(ValueError):
                parse_command(payload)
        for serial, expected in (("345046", 345046), ("000456", 456),
                                 ("1", 1), ("4294967295", 0xFFFFFFFF)):
            self.assertEqual(parse_command(json.dumps({"receiver_id": serial, "command": "on"})),
                             (expected, "ON"))
        for serial in (True, 0, -1, 2**32, 1.5, None, "", "0", "-1", "4294967296",
                       "1.5", " 456", "+456", "４５６", "abc"):
            with self.subTest(serial=serial), self.assertRaises(ValueError):
                parse_command(json.dumps({"receiver_id": serial, "command": "on"}))
        for command in ("toggle", "stepOpen", "stepClose", "open", "close", "stop", "ON", None, []):
            with self.subTest(command=command), self.assertRaises(ValueError):
                parse_command(json.dumps({"receiver_id": 456, "command": command}))

    def test_callback_guards_and_bounded_queue(self):
        commands = queue.Queue(maxsize=1)
        ready = threading.Event()
        message = SimpleNamespace(topic=COMMAND_TOPIC, retain=False,
                                  payload=b'{"receiver_id":456,"command":"on"}')
        with self.assertLogs("mqtt_service", level="WARNING"):
            receive_command(message, commands, ready)
        self.assertTrue(commands.empty())
        ready.set()
        message.retain = True
        with self.assertLogs("mqtt_service", level="WARNING"):
            receive_command(message, commands, ready)
        self.assertTrue(commands.empty())
        message.retain = False
        receive_command(message, commands, ready)
        with self.assertLogs("mqtt_service", level="WARNING"):
            receive_command(message, commands, ready)
        self.assertEqual(commands.get_nowait(), (456, "ON"))

    def test_confirmation_matches_ack_addresses_only(self):
        wait = ConfirmationWait()
        packet = build_switch_command(456, "ON", 0x11)
        with self.assertLogs("mqtt_service", level="INFO"):
            wait.start(packet, "ON", 10.0)
        ack = {"sender_id": 456, "receiver_id": 128,
               "other": {"message": "ACKNOWLEDGEMENT"}}
        for unrelated in (
                dict(ack, sender_id=789), dict(ack, receiver_id=789),
                dict(ack, other={"message": "LEGACY STATUS"}), dict(ack, other={})):
            wait.observe(unrelated, 11.0)
            self.assertIsNotNone(wait.pending)
        with self.assertLogs("mqtt_service", level="INFO") as logs:
            wait.observe(ack, 12.9)
        self.assertIsNone(wait.pending)
        self.assertIn("Radio acknowledgement received", logs.output[0])
        wait.observe(ack, 12.95)  # Duplicate ACK cannot confirm another command.
        self.assertIsNone(wait.pending)

    def test_confirmation_timeout_late_ack_and_interruption(self):
        wait = ConfirmationWait()
        packet = build_switch_command(456, "OFF", 0x11)
        with self.assertLogs("mqtt_service", level="INFO"):
            wait.start(packet, "OFF", 10.0)
        wait.expire(12.99)
        self.assertIsNotNone(wait.pending)
        ack = {"sender_id": 456, "receiver_id": 128,
               "other": {"message": "ACKNOWLEDGEMENT"}}
        with self.assertLogs("mqtt_service", level="WARNING") as logs:
            wait.observe(ack, 13.0)
        self.assertIsNone(wait.pending)
        self.assertIn("no matching acknowledgement", logs.output[0])
        with self.assertLogs("mqtt_service", level="INFO"):
            wait.start(packet, "OFF", 20.0)
        with self.assertLogs("mqtt_service", level="WARNING"):
            wait.cancel("radio connection failed")
        self.assertIsNone(wait.pending)
        wait.cancel("service stopping")

    @patch("linux_reader.os.write", return_value=63)
    def test_usb_padding_sequence_and_failed_write(self, write):
        reader = Reader.__new__(Reader)
        reader.fd = 8
        reader.sequence = 0x1F
        packet = reader.send_switch(456, "ON")
        write.assert_called_once_with(8, b"\0" + packet + bytes(39))
        self.assertEqual(reader.sequence, 0x10)
        write.return_value = 1
        with self.assertRaises(OSError):
            reader.send_switch(456, "OFF")
        self.assertEqual(reader.sequence, 0x10)


if __name__ == "__main__":
    unittest.main()
