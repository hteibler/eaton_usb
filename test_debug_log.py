import json
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import unittest

from debug_log import configure_debug, traffic
from mqtt_service import receive_command


class DebugLogTests(unittest.TestCase):
    def tearDown(self):
        configure_debug('false')

    def test_disabled_creates_no_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'debug.log'
            configure_debug('false', path)
            traffic('MQTT RX', b'test')
            self.assertFalse(path.exists())
        with self.assertRaises(ValueError):
            configure_debug('maybe')

    def test_complete_payload_timestamp_and_safe_line_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'debug.log'
            configure_debug('true', path)
            payload = b'hello\n\xff\x00'
            traffic('SERIAL RX', payload)
            line = path.read_text()
            self.assertEqual(len(line.splitlines()), 1)
            self.assertRegex(line, r'^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d - SERIAL RX ')
            record = json.loads(line.split('SERIAL RX ', 1)[1])
            self.assertEqual(bytes.fromhex(record['hex']), payload)
            configure_debug('false')
            traffic('MQTT RX', b'not recorded')
            self.assertEqual(path.read_text(), line)

    def test_rejected_mqtt_payload_is_logged_completely(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'debug.log'
            configure_debug('true', path)
            message = SimpleNamespace(topic='eaton/eaton_usb_do', retain=True,
                                      payload=b'{"receiver_id":456,"command":"on"}')
            with self.assertLogs('mqtt_service', level='WARNING'):
                receive_command(message, queue.Queue(), threading.Event())
            record = json.loads(path.read_text().split('MQTT RX ', 1)[1])
            self.assertEqual(record['payload'], message.payload.decode())
            self.assertTrue(record['retain'])
            self.assertEqual(record['topic'], message.topic)


if __name__ == '__main__':
    unittest.main()
