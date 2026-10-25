import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from linux_reader import Reader
from mqtt_bridge import event_from_report, load_devices


def frame(kind=0x54, sender=534129, side=0):
    report = bytearray(22)
    report[:4] = bytes((0x5A, 22, 3, kind))
    report[9] = side
    report[10:14] = sender.to_bytes(4, "little")
    report[15:19] = (123).to_bytes(4, "little")
    report[-3:-1] = (-750).to_bytes(2, "little", signed=True)
    report[-1] = 0xA5
    return bytes(report)


class BridgeTests(unittest.TestCase):
    def test_action_mapping_and_names(self):
        for kind, action in ((0x50, "ON"), (0x51, "OFF"), (0x54, "ON_PRESSED"),
                             (0x55, "ON_RELEASED"), (0x56, "OFF_PRESSED"), (0x57, "OFF_RELEASED")):
            with self.subTest(kind=kind):
                event = event_from_report(frame(kind), {534129: ("Küche", "Taster")})
                self.assertEqual(event["action"], action)
                self.assertNotIn("command", event["other"])
                self.assertEqual(event["sender_name"], "Küche")
                self.assertEqual(event["sender_type"], "Taster")
                self.assertEqual(event["receiver_id"], 123)
                self.assertEqual(event["receiver_name"], "")
                self.assertEqual(event["button"], "LEFT")

    def test_side_is_only_inferred_for_observed_sender(self):
        self.assertEqual(event_from_report(frame(side=1), {})["button"], "RIGHT")
        self.assertEqual(event_from_report(frame(sender=456), {})["button"], "N/A")
        self.assertEqual(event_from_report(frame(side=2), {})["button"], "N/A")

    def test_other_two_button_devices(self):
        devices = {8225718: ("Example switch", "Taster 2-fach")}
        for kind in (0x50, 0x51, 0x54, 0x55, 0x56, 0x57):
            for side, expected in ((0, "LEFT"), (1, "RIGHT"), (2, "N/A")):
                with self.subTest(kind=kind, side=side):
                    event = event_from_report(frame(kind, sender=8225718, side=side), devices)
                    self.assertEqual(event["button"], expected)
        self.assertEqual(event_from_report(frame(1, sender=8225718), devices)["button"], "N/A")
        for device_type in ("Taster 4-fach", "Schaltaktor", ""):
            self.assertEqual(event_from_report(frame(sender=8225718),
                             {8225718: ("Example", device_type)})["button"], "N/A")

    def test_report_id_padding_and_invalid_frames(self):
        good = frame()
        self.assertEqual(event_from_report(good, {}),
                         event_from_report(b"\0" + good + bytes(40), {}))
        for bad in (b"", b"\x5a", good[:-1], good[:-1] + b"\0",
                    good[:2] + b"\x04" + good[3:], bytes((0x5A, 7, 3, 1, 0, 0, 0xA5))):
            self.assertIsNone(event_from_report(bad, {}))

    def test_unknown_and_auxiliary_fields(self):
        unknown = event_from_report(frame(0x99), {})
        self.assertEqual(unknown["action"], "N/A")
        self.assertEqual(unknown["other"]["message"], "UNKNOWN TYPE 0x99")
        self.assertIn("raw", unknown["other"])
        self.assertEqual(event_from_report(frame(1), {})["other"]["message"], "ACKNOWLEDGEMENT")
        report = bytearray(frame(0x56))
        report[7] = 0x10
        self.assertEqual(event_from_report(report, {})["other"], {"repeat": True})
        report[3] = 0x70
        report[14] = 42
        self.assertEqual(event_from_report(report, {})["other"]["receiver_data_point"], 42)

    def test_csv_preserves_names(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "devices.csv"
            path.write_text("\ufeffGerätename,Gerätetype,Seriennummer\nKüche,Taster,123\nX,Y,invalid\n", encoding="utf-8")
            self.assertEqual(load_devices(path), {123: ("Küche", "Taster")})

    @patch("linux_reader.os.close")
    @patch("linux_reader.fcntl.ioctl")
    @patch("linux_reader.os.open", return_value=8)
    def test_wrong_device_is_closed(self, open_device, ioctl, close_device):
        with self.assertRaises(RuntimeError):
            Reader("/dev/test")
        close_device.assert_called_once_with(8)

    @patch("linux_reader.os.write", return_value=63)
    def test_reception_command(self, write):
        reader = Reader.__new__(Reader)
        reader.fd = 8
        reader.enable_reception()
        write.assert_called_once_with(8, b"\0" + bytes.fromhex("5a 05 1a 01 a5") + bytes(57))
        write.return_value = 1
        with self.assertRaises(OSError):
            reader.enable_reception()


if __name__ == "__main__":
    unittest.main()
