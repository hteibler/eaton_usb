# Eaton USB to MQTT

Linux Docker service for the Eaton xComfort CKOZ-00/13 USB stick (`188a:1102`).
The existing Windows monitor is preserved below. The service reuses its decoder
and sends only the observed reception-enable command, never radio control commands.

## Features

- Headless Linux USB-to-MQTT bridge with Docker Compose deployment.
- Sender and receiver serial numbers, CSV device names and sender device types.
- Combined actions: `ON_PRESSED`, `ON_RELEASED`, `OFF_PRESSED`, `OFF_RELEASED`,
  plus plain `ON` and `OFF` telegrams.
- LEFT/RIGHT identification for `Taster 2-fach` switches, using the DT1 layout.
- English acknowledgement, legacy status and unknown-message descriptions.
- Repeat indicators, receiver data points and raw data for unclassified messages.
- MQTT reconnection, USB retries, graceful shutdown and bounded container logs.
- Non-root container with one USB device, read-only files and no extra capabilities.
- Original Windows GUI monitor and CSV recording remain available.

## Docker setup (Linux)

1. Close Eaton MRF and other programs using the stick.
   On a fresh checkout, copy `smarthome_devices.example.csv` to
   `smarthome_devices.csv` and replace its synthetic entries with your device list.
   Existing local inventories should be preserved. Personal device inventories
   and credentials are not included in the repository.
2. Copy `.env.example` to `.env` if `.env` does not already exist. Set the MQTT
   host, port, username and password there. Keep this file private; it is excluded
   from Git and the Docker build context. Compose loads it automatically.
   Use single quotes around passwords containing `$` or `#` in the Compose env file.
3. Identify the Eaton hidraw node using
   `cat /sys/class/hidraw/hidraw*/device/uevent`: match
   `HID_ID=0003:0000188A:00001102` to its enclosing `hidrawN` directory.
   Set `EATON_DEVICE=/dev/hidrawN` in `.env` (default `/dev/hidraw1`).
4. Run `stat -c '%g %a' /dev/hidrawN`. Set `EATON_GID` to the numeric owning
   group. That group must have read/write permission on the node. If it does not,
   arrange a narrowly scoped host udev rule for this device before starting.
   The container runs as UID 10001 with only the selected device passed through.
5. Run `docker compose up --build -d`, then `docker compose logs -f`.
   Stop and remove the container with `docker compose down`.

MQTT uses unencrypted TCP on port 1883, as requested; use a trusted private network.
Device names and types are loaded unchanged from `smarthome_devices.csv` at
startup. Edit that file and restart the service to reload it.

### Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `MQTT_HOST` | `192.168.99.95` | Broker hostname or IP address |
| `MQTT_PORT` | `1883` | Broker TCP port |
| `MQTT_USERNAME` | empty | Optional broker username |
| `MQTT_PASSWORD` | empty | Optional password; requires a username |
| `EATON_DEVICE` | `/dev/hidraw1` | Host Eaton device passed into the container |
| `EATON_GID` | `0` | Host device group added to the container user |

Compose sets the service's `USB_DEVICE=/dev/eaton` and
`DEVICES_FILE=/app/smarthome_devices.csv`. The CSV must have the columns
`Gerätename`, `Gerätetype`, and `Seriennummer`; serial numbers must be decimal.

### Updating and troubleshooting

After changing Python code or requirements, rebuild and recreate the service:

```bash
docker compose up --build -d
docker compose logs -f
```

`MQTT connected` confirms broker access. `USB reception enabled` confirms the
stick was opened and the reception-enable command was written. Successful startup
alone does not verify physical button decoding or MQTT delivery.

If logs show `USB unavailable (Permission denied)`, check the host node's mode
and group with `stat -c '%g %a' /dev/hidrawN`. Mode `600` permits only its owner,
so adding the device group to the container alone is insufficient. For the
verified Eaton node, an administrator can temporarily grant the owning group
read/write access with `sudo chmod g+rw /dev/hidrawN`. Set `EATON_GID` to that
group's numeric ID. This permission change is lost when the device is recreated;
use a host udev rule restricted to USB vendor `188a` and product `1102` for
persistent access. Do not change permissions on unrelated hidraw devices.

USB access is attempted after MQTT connects. If no USB startup message appears,
first check broker address, reachability and credentials. A wrong device identity
is rejected; recheck the hidraw node after reconnecting the stick.

## MQTT payload

Events are JSON on `eaton/eaton_usb/<sender serial number>`, QoS 1, never retained:

```json
{"sender_id":123,"sender_name":"Example switch","sender_type":"Taster","receiver_id":456,"receiver_name":"Example light","button":"N/A","action":"ON","other":{}}
```

A two-button switch press uses a combined action, for example:

```json
{"sender_id":123,"sender_name":"Example switch","sender_type":"Taster 2-fach","receiver_id":456,"receiver_name":"Example light","button":"LEFT","action":"ON_PRESSED","other":{}}
```

| Radio type | `action` |
| --- | --- |
| `0x50` | `ON` |
| `0x51` | `OFF` |
| `0x54` | `ON_PRESSED` |
| `0x55` | `ON_RELEASED` |
| `0x56` | `OFF_PRESSED` |
| `0x57` | `OFF_RELEASED` |
| Other | `N/A` |

IDs are numbers; missing names/types are empty strings. Actions are `ON`, `OFF`,
`ON_PRESSED`, `ON_RELEASED`, `OFF_PRESSED`, `OFF_RELEASED`, or `N/A`.
Press/release actions combine the command and state in one name; consumers of the
previous `PRESSED`/`RELEASED` and `other.command` representation must use `action`
instead. `other.repeat` marks repeats, and `other.receiver_data_point` preserves
status addressing. Acknowledgements, legacy status and unknown types have English
messages in `other.message` plus raw hex. Names and device types retain the CSV's
original language. Malformed frames and non-radio USB replies are discarded.

LEFT/RIGHT uses byte 9 (`0` = LEFT, `1` = RIGHT) for devices whose CSV type is
`Taster 2-fach`, and for DT1 (sender 534129) even without a CSV entry. This layout
was verified for DT1 and is assumed to apply to the same device class; confirm it
with physical presses on other models. Other device types and unrecognized side
values use `N/A`.

The service retries broker connections and USB access. A pending QoS 1 event waits
for acknowledgement before more USB reports are read, so a prolonged broker
outage can overflow the stick/kernel buffer. There is no disk queue; process
restarts can lose pending events, and QoS 1 can duplicate messages. USB replugging
may change the node; update `.env` and recreate the container if necessary.

## Code and functions

| File | Main functions and responsibilities |
| --- | --- |
| `mqtt_service.py` | `main()` loads configuration, starts MQTT, handles signals, reads USB reports, publishes JSON and retries USB failures |
| `mqtt_bridge.py` | `load_devices()` reads device names/types; `event_from_report()` validates radio frames and creates payloads |
| `linux_reader.py` | `Reader` validates USB identity; `enable_reception()`, `read()` and `close()` manage Linux hidraw access |
| `protocol.py` | `decode()` extracts IDs, message type, battery information, RSSI, reception quality, data point and raw bytes |
| `app.py` | Windows GUI, device labels and timestamped CSV recordings |
| `hid_reader.py` | Original Windows HID transport |
| `test_bridge.py` | Synthetic regression tests for actions, button sides, frame validation, CSV names and USB transport |
| `verify_capture.py` | Historical decoder comparison against original MRF exports and USB captures |

Battery, RSSI and reception quality are decoded by `protocol.py` for the Windows
monitor but are not fields in the current MQTT payload.

## Verification

Run `python3 -m unittest -v test_bridge` for synthetic frame and transport tests.
Run `docker compose config --quiet` to validate configuration without displaying
credentials. A live smoke test requires building the image and checking events
against physical button presses using a broker subscriber to `eaton/eaton_usb/#`.
The older `verify_capture.py` requires the original Windows capture files and
Wireshark; it is separate from these tests.

## Original Windows monitor

Eigenständiger, lesender Windows-Monitor für den Eaton xComfort Konfigurationsstick
**CKOZ-00/13** (USB `188A:1102`). Er zeigt die vom Stick gelieferten Telegramme live an
und speichert sie fortlaufend als CSV im Programmordner.

### Start

1. Eaton MRF schließen, damit es den Stick freigibt.
2. `Start Funkmonitor.bat` doppelklicken. Python 3.9 oder neuer muss installiert sein.
3. **Aufzeichnung starten** wählen.

Das Programm verwendet nur die Python-Standardbibliothek. Es sendet beim Start
den in einer MRF-USB-Aufzeichnung beobachteten Befehl zum Aktivieren des Empfangs.
Beim Start wird automatisch eine Datei `eaton-monitor-*.csv` angelegt.
Die CSV enthält auch die Rohdaten jedes Telegramms.
Gerätenamen werden aus `smarthome_devices.csv` (Spalten `Gerätename` und
`Seriennummer`) geladen. Änderungen daran werden beim nächsten Start der
Aufzeichnung übernommen.
In der Anzeige bleibt die Geräte-ID neben dem Namen sichtbar.

### Stand der Decodierung

Die Meldungstypen **Ein**, **Aus**, **Bestätigung** und **Status alt** sowie Absender,
Empfänger, Wiederholungen und Empfangsqualität wurden mit einer gleichzeitigen
USB-Aufzeichnung und dem MRF-2.78-Monitorexport abgeglichen. Für bislang unbekannte
Typen zeigt die Anwendung den Typcode und die vollständigen Rohdaten.

Die Protokoll-Decodierung wurde gegen 62 MRF-Telegramme geprüft. Der direkte
Empfang am CKOZ-00/13 wurde anschließend getestet; sechs Funktelegramme wurden
ohne laufendes MRF empfangen und als CSV gespeichert. In der Liste bleiben die
letzten 5000 Telegramme sichtbar, die CSV enthält weiterhin alle.

Der Meldungstyp **AUSSCHALTEN** ist im MRF-Export enthalten, lag aber vor Beginn
der zugehörigen USB-Aufnahme. Er wird bei einem künftigen Auftreten derzeit als
Typcode und Rohdaten angezeigt, bis ein passendes USB-Telegramm vorliegt.
