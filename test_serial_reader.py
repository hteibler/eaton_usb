import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mqtt_bridge import event_from_report
from mqtt_service import reader_class
from linux_reader import Reader as HidReader
from protocol import build_switch_command
from serial_reader import Reader


class SerialTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock(is_open=True)
        self.connection.write.side_effect = len
        self.module = SimpleNamespace(Serial=Mock(return_value=self.connection))
        with patch.dict(sys.modules, serial=self.module):
            self.reader = Reader('/dev/test')

    def test_selection_and_port_settings(self):
        self.assertIs(reader_class('hid'), HidReader)
        self.assertIs(reader_class('serial'), Reader)
        with self.assertRaises(ValueError):
            reader_class('invalid')
        self.module.Serial.assert_called_once_with(
            '/dev/test', 115200, bytesize=8, parity='N', stopbits=1,
            timeout=0.25, write_timeout=3)

    def test_startup_and_switch_sequence(self):
        self.reader.enable_reception()
        self.assertEqual([call.args[0] for call in self.connection.write.call_args_list],
                         [bytes.fromhex('5a 04 0b a5'), bytes.fromhex('5a 05 1a 01 a5')])
        self.reader.sequence = 0x1F
        packet = self.reader.send_switch(456, 'ON')
        self.assertEqual(packet, build_switch_command(456, 'ON', 0x1F))
        self.connection.write.assert_called_with(packet)
        self.assertEqual(self.reader.sequence, 0x10)
        self.connection.write.side_effect = None
        self.connection.write.return_value = 1
        with self.assertRaises(OSError):
            self.reader.send_switch(456, 'OFF')
        self.assertEqual(self.reader.sequence, 0x10)

    def test_fragmented_coalesced_frames_and_timeout(self):
        reply = bytes.fromhex('5a 04 0b a5')
        frame = bytes.fromhex('5a 16 03 50 00 00 00 00 04 00 7b 00 00 00 00 c8 01 00 00 12 fd a5')
        self.connection.read.side_effect = [b'noise\x5a\x02\x5a\x05\x00\x00\x00' + reply + frame[:7], b'', frame[7:], b'']
        self.assertEqual(self.reader.read(), reply)
        self.assertEqual(self.reader.read(), b'')
        self.assertEqual(self.reader.read(), frame)
        self.assertEqual(event_from_report(frame, {})['sender_id'], 123)
        self.assertEqual(self.reader.read(), b'')

    def test_disconnect_and_close(self):
        self.connection.read.side_effect = OSError('disconnected')
        with self.assertRaises(OSError):
            self.reader.read()
        self.reader.close()
        self.connection.close.assert_called_once()
        self.connection.is_open = False
        self.assertEqual(self.reader.read(), b'')
        with self.assertRaises(OSError):
            self.reader.send_switch(456, 'ON')


if __name__ == '__main__':
    unittest.main()
