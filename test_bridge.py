import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from linux_reader import Reader
from mqtt_bridge import event_from_report, load_devices
from protocol import decode


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
                event = event_from_report(frame(kind), {534129: ("Küche", "Taster 2-fach")})
                self.assertEqual(event["action"], action)
                self.assertNotIn("command", event["other"])
                self.assertEqual(event["sender_name"], "Küche")
                self.assertEqual(event["sender_type"], "Taster 2-fach")
                self.assertEqual(event["receiver_id"], 123)
                self.assertEqual(event["receiver_name"], "")
                self.assertEqual(event["button"], "LEFT")

    def test_device_ids_do_not_override_missing_types(self):
        self.assertEqual(event_from_report(frame(side=1), {})["button"], "N/A")
        self.assertEqual(event_from_report(frame(sender=534944), {})["button"], "N/A")
        self.assertEqual(event_from_report(frame(sender=456), {})["button"], "N/A")
        self.assertEqual(event_from_report(frame(side=2), {})["button"], "N/A")
        self.assertEqual(decode(frame()).message, "ON PRESSED")

    def test_other_two_button_devices(self):
        devices = {8225718: ("Example switch", "Taster 2-fach")}
        for kind in (0x50, 0x51, 0x54, 0x55, 0x56, 0x57):
            for side, expected in ((0, "LEFT"), (1, "RIGHT"), (2, "N/A")):
                with self.subTest(kind=kind, side=side):
                    event = event_from_report(frame(kind, sender=8225718, side=side), devices)
                    self.assertEqual(event["button"], expected)
        self.assertEqual(event_from_report(frame(1, sender=8225718), devices)["button"], "N/A")
        for device_type in ("Schaltaktor", ""):
            self.assertEqual(event_from_report(frame(sender=8225718),
                             {8225718: ("Example", device_type)})["button"], "N/A")

    def test_four_button_switch(self):
        # Synthetic IDs; channel bytes and frame layout follow the supplied CTAA capture.
        capture = bytearray.fromhex(
            "5A 1B 03 50 00 13 15 02 04 00 01 00 00 00 00 "
            "02 00 00 00 00 F7 C7 2C ED F4 FC A5")
        for device_type in ("Taster 4-fach", "CTAA-04/04"):
            devices = {1: ("Example four-button switch", device_type)}
            for code, expected in ((0, "1"), (1, "2"), (2, "3"), (3, "4")):
                for receiver in (0, 2):
                    capture[9] = code
                    capture[15:19] = receiver.to_bytes(4, "little")
                    event = event_from_report(capture, devices)
                    self.assertEqual(event["button"], expected)
                    self.assertEqual(event["action"], "ON")
            for code in (4, 255):
                self.assertEqual(event_from_report(frame(0x50, sender=1, side=code),
                                                  devices)["button"], "N/A")
            for kind in (1, 0x70, 0x99):
                self.assertEqual(event_from_report(frame(kind, sender=1), devices)["button"], "N/A")
            # Other control actions reuse the channel field; physical verification pending.
            for kind in (0x51, 0x54, 0x55, 0x56, 0x57):
                self.assertEqual(event_from_report(frame(kind, sender=1, side=3),
                                                  devices)["button"], "4")
        self.assertEqual(event_from_report(capture, {})["button"], "N/A")

    def test_remote_channel_buttons(self):
        devices = {456: ("Example remote", "Fernbedienung")}
        # Explicit expectations follow the user's confirmed recording order.
        labels = ("1-LEFT", "1-RIGHT", "2-LEFT", "2-RIGHT", "3-LEFT", "3-RIGHT",
                  "4-LEFT", "4-RIGHT", "5-LEFT", "5-RIGHT", "6-LEFT", "6-RIGHT")
        for code, expected in enumerate(labels):
            with self.subTest(code=code):
                event = event_from_report(frame(0x50, sender=456, side=code), devices)
                self.assertEqual(event["button"], expected)
                self.assertEqual(event["action"], "ON")
        for kind, action in ((0x51, "OFF"), (0x54, "ON_PRESSED"),
                             (0x55, "ON_RELEASED"), (0x56, "OFF_PRESSED"),
                             (0x57, "OFF_RELEASED")):
            event = event_from_report(frame(kind, sender=456, side=11), devices)
            self.assertEqual(event["button"], "6-RIGHT")
            self.assertEqual(event["action"], action)
        for code in (12, 255):
            self.assertEqual(event_from_report(frame(sender=456, side=code), devices)["button"], "N/A")
        self.assertEqual(event_from_report(frame(1, sender=456), devices)["button"], "N/A")
        self.assertEqual(event_from_report(frame(0x99, sender=456), devices)["button"], "N/A")
        self.assertEqual(event_from_report(frame(sender=456, side=11), {})["button"], "N/A")

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

    def test_power_supply_values(self):
        for code, expected in ((3, "BATTERY_NEARLY_FULL"), (4, "BATTERY_FULL"),
                               (0xAB, "CODE 0xAB")):
            report = bytearray(frame())
            report[8] = code
            self.assertEqual(event_from_report(report, {})["power_supply"], expected)
        for kind in (1, 0x70):
            self.assertEqual(event_from_report(frame(kind), {})["power_supply"], "MAINS_POWERED")
        self.assertEqual(event_from_report(frame(0x99), {})["power_supply"], "N/A")

    def test_reception_and_raw_fields(self):
        for rssi_tenths, expected_percent in ((-750, 52), (-1010, 0),
                                               (-510, 100), (-1100, 0), (-400, 100)):
            report = bytearray(frame())
            report[-3:-1] = rssi_tenths.to_bytes(2, "little", signed=True)
            event = event_from_report(b"\0" + report + bytes(40), {})
            self.assertEqual(event["rssi_dbm"], rssi_tenths / 10)
            self.assertEqual(event["reception_percent"], expected_percent)
            self.assertEqual(event["raw"], report.hex(" ").upper())
        unknown = event_from_report(frame(0x99), {})
        self.assertEqual(unknown["raw"], unknown["other"]["raw"])

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
