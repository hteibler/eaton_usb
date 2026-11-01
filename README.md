# Eaton USB to MQTT

Linux Docker service for the Eaton xComfort CKOZ-00/13 USB stick (`188a:1102`)
or the CRSZ-00/01 serial radio via FT232 UART (`0403:6001`).
The existing Windows monitor is preserved below. The service reuses its decoder
and uses the captured on/off transmit frames supplied in `other_code`.

## Features

- Headless Linux USB-to-MQTT bridge with Docker Compose deployment.
- Sender and receiver serial numbers, CSV device names and sender device types.
- Combined actions: `ON_PRESSED`, `ON_RELEASED`, `OFF_PRESSED`, `OFF_RELEASED`,
  plus plain `ON` and `OFF` telegrams.
- LEFT/RIGHT identification for `Taster 2-fach` switches, using the DT1 layout.
- Channel/rocker labels `1-LEFT` through `6-RIGHT` for the captured six-channel remote.
- English acknowledgement, legacy status and unknown-message descriptions.
- Repeat indicators, receiver data points and raw data for unclassified messages.
- Power supply status, reception percentage, RSSI in dBm and raw hex on every event.
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

### Serial radio (Phase 3)

Compose selects the transport with `EATON_TRANSPORT` (default `hid`). For the
FT232 serial radio, set these entries in `.env`:

```dotenv
EATON_TRANSPORT=serial
EATON_DEVICE=/dev/ttyUSB0
```

Verify the actual port belongs to your radio; the USB bus/device number is not
its serial port path. A stable `/dev/serial/by-id/...` path can also be used.
FT232 IDs identify a generic UART adapter, so they alone do not identify the radio.
Set `EATON_GID` to the numeric group from `stat -c '%g %a' /dev/ttyUSB0` and ensure
that group already has read/write access. Compose maps the selected device to
`/dev/eaton` for either transport without granting access to other devices.

Run `docker compose up --build -d` to rebuild and recreate the service. Serial
uses 115200 baud, 8N1, the identification/reception probes from
`other_code/serial_reader.py`, and the existing MQTT decoder and on/off commands.
Idle reads return regularly so commands and shutdown remain responsive.
The container includes `pyserial`; no host Python package is needed for Docker.
Hardware reception and actuator delivery still require a live smoke test.

To return to the original stick, set `EATON_TRANSPORT=hid`, restore its
`EATON_DEVICE` and `EATON_GID`, and recreate the service. The original HID reader
and Windows monitor remain available. Neither transport is opened concurrently.

Log timestamps use `Europe/Vienna` (CET/CEST, including daylight-saving changes).
Compose mounts the host’s `/usr/share/zoneinfo/Europe/Vienna` timezone file read-only;
that file must exist on the Docker host.

### Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `MQTT_HOST` | `192.168.99.95` | Broker hostname or IP address |
| `MQTT_PORT` | `1883` | Broker TCP port |
| `MQTT_USERNAME` | empty | Optional broker username |
| `MQTT_PASSWORD` | empty | Optional password; requires a username |
| `EATON_TRANSPORT` | `hid` | `hid` for the original stick or `serial` for the FT232 radio |
| `EATON_DEVICE` | `/dev/hidraw1` | Host Eaton device passed into the container |
| `EATON_GID` | `0` | Host device group added to the container user |

Compose sets the service's `USB_DEVICE=/dev/eaton` and
`DEVICES_FILE=/app/smarthome_devices.csv`. The CSV must have the columns
`Gerätename`, `Gerätetype`, and `Seriennummer`; serial numbers must be decimal.

### Debug traffic log

Set `DEBUG=true` in `.env`, then run `docker compose up --build -d`.
The default is `DEBUG=false`. The log records full incoming MQTT payloads
(including rejected commands), outgoing MQTT publish attempts and their result
codes, and all non-empty raw radio reads/writes, including startup commands.
Labels identify `MQTT RX`, `MQTT TX`, `HID RX/TX`, or `SERIAL RX/TX`.
Timestamps include the date and local `Europe/Vienna` time. Binary traffic is
preserved in full as hex; serial reads are chunks and may contain partial or
multiple frames. A logged write/publish attempt does not confirm delivery.

Docker stores `/app/logs/debug.log` in the persistent `debug-logs` volume,
with only that directory writable. To view it or copy it to the project folder:

```bash
docker compose exec eaton-usb tail -f /app/logs/debug.log
docker compose cp eaton-usb:/app/logs/debug.log ./debug.log
```

Logs rotate at 5 MB with two backups (`debug.log.1` and `debug.log.2`); older
traffic is discarded. The file survives container recreation. Set `DEBUG=false`
and run `docker compose up -d` to stop recording; existing logs remain.
Credentials and connection settings are not recorded, but full event payloads
include your device names and activity. Debug logs are excluded from Git.
For running Python directly, the default path is `debug.log` in the working
directory; `DEBUG_LOG` can override it.

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

To install the supplied persistent rule on the Docker host (requires administrator
approval), run from the repository directory:

```bash
sudo install -m 0644 udev/99-eaton-usb.rules /etc/udev/rules.d/99-eaton-usb.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --action=change /sys/class/hidraw/hidrawN
```

Replace `hidrawN` with the verified Eaton node before triggering the rule.

The rule grants group `root` read/write access only to Eaton `188a:1102` hidraw
nodes, and creates `/dev/eaton`. Use `EATON_GID=0` with this rule. Set
`EATON_DEVICE=/dev/eaton` in `.env` to use the stable host alias, then recreate
the container with `docker compose up -d --force-recreate eaton-usb` so its
existing device node receives the new permissions. Future reconnects recreate
the host device with the same permissions. Docker pins the device number at
container creation: if it changes after reconnecting, recreate the container
again to refresh the mapping even when using the stable alias.

To roll back, remove only `/etc/udev/rules.d/99-eaton-usb.rules`, reload udev
rules, and reconnect the stick. This restores the host's default permissions;
the container must be recreated to refresh its device node permissions.

USB access is attempted after MQTT connects. If no USB startup message appears,
first check broker address, reachability and credentials. A wrong device identity
is rejected; recheck the hidraw node after reconnecting the stick.

## MQTT payload

Events are JSON on `eaton/eaton_usb/<sender serial number>`, QoS 1, retained.
The broker keeps the latest event for each sender and delivers it to new
subscribers. These are observed events, not confirmed actuator states:

```json
{"sender_id":123,"sender_name":"Example switch","sender_type":"Taster","receiver_id":456,"receiver_name":"Example light","button":"N/A","action":"ON","power_supply":"BATTERY_FULL","reception_percent":52,"rssi_dbm":-75.0,"raw":"5A 16 03 50 00 00 00 00 04 00 7B 00 00 00 00 C8 01 00 00 12 FD A5","other":{}}
```

A two-button switch press uses a combined action, for example:

```json
{"sender_id":123,"sender_name":"Example switch","sender_type":"Taster 2-fach","receiver_id":456,"receiver_name":"Example light","button":"LEFT","action":"ON_PRESSED","power_supply":"BATTERY_FULL","reception_percent":52,"rssi_dbm":-75.0,"raw":"5A 16 03 54 00 00 00 00 04 00 7B 00 00 00 00 C8 01 00 00 12 FD A5","other":{}}
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

Every payload also contains these decoded telemetry fields:

| Field | Value |
| --- | --- |
| `power_supply` | `MAINS_POWERED`, `BATTERY_FULL`, `BATTERY_NEARLY_FULL`, `CODE 0xNN` for an unknown battery code, or `N/A` when unavailable |
| `reception_percent` | Integer from 0 to 100; the decoder maps -101 dBm to 0% and -51 dBm to 100%, clamping outside that range |
| `rssi_dbm` | Signed numeric signal strength in dBm, for example `-75.0` |
| `raw` | Complete validated telegram as uppercase, space-separated hex, excluding HID report ID and padding |

The existing `other.raw` remains present for unclassified messages for compatibility.

LEFT/RIGHT uses byte 9 (`0` = LEFT, `1` = RIGHT) for devices whose CSV type is
`Taster 2-fach`. This layout
was verified for DT1 and is assumed to apply to the same device class; confirm it
with physical presses on other models. Other device types and unrecognized side
values use `N/A`.

For the CTAA-04/04 four-button switch, set CSV `Gerätetype` to `Taster 4-fach`
or `CTAA-04/04`. Byte 9 values `00`, `01`, `02`, `03` map to string values
`"1"`, `"2"`, `"3"`, `"4"` in `button`. The supplied ON-only capture confirms
these four channel codes; OFF and press/release actions reuse the mapping but
still need physical verification. `action` remains separate, for example
`"button":"1","action":"ON"`. Codes outside 0–3 and non-control messages use
`N/A`. Mapping works for both addressed telegrams and receiver ID 0.

If `sender_name` and `sender_type` are empty and `button` is `N/A`, add the
switch to the mounted `smarthome_devices.csv`. Button identification requires a
recognized CSV type; it is not inferred from a serial number. For example, using
a synthetic serial number (replace it with the sender ID shown in your event):

```csv
Gerätename,Gerätetype,Seriennummer
Example four-button switch,Taster 4-fach,123
```

Keep the existing header and inventory rows; add or update only the relevant
switch row using the file's existing column order. Run
`docker compose restart eaton-usb` to reload the CSV. On the next press, channel
`03` produces `"button":"4","action":"ON"`. If `sender_type` is still empty,
verify that the file you edited is the CSV mounted by Compose. Existing retained
MQTT events are replaced only when a new event from that sender is published.

For devices whose CSV type is `Fernbedienung`, `button` combines the channel
and rocker: `1-LEFT`, `1-RIGHT`, `2-LEFT`, `2-RIGHT`, through `6-LEFT`, `6-RIGHT`.
Byte 9 values `00`/`01` identify channel 1, `02`/`03` channel 2, through
`0A`/`0B` for channel 6. This sequence was confirmed from the supplied upper-button
capture. `action` remains separate (for example `ON`); lower-button and hold/release
events reuse that channel/rocker mapping but still need physical verification.
Unknown codes and non-control messages use `N/A`. The mapping applies to all
devices with CSV type `Fernbedienung`; it was confirmed on the captured six-channel
model, so verify it on other models. Button decoding depends entirely on CSV type,
with no sender-serial exceptions. Missing or unrecognized device types use `N/A`.

The service retries broker connections and USB access. A pending QoS 1 event waits
for acknowledgement before more USB reports are read, so a prolonged broker
outage can overflow the stick/kernel buffer. There is no disk queue; process
restarts can lose pending events, and QoS 1 can duplicate messages. USB replugging
may change the node; update `.env` and recreate the container if necessary.

## MQTT actuator commands

Publish a non-retained JSON message to `eaton/eaton_usb_do`:

```json
{"receiver_id":456,"command":"on"}
```

`receiver_id` accepts an integer or an ASCII decimal string (for example
`"345046"`) from 1 to 4294967295. Supported commands are
`on` and `off`. `toggle`, `stepOpen`, `stepClose`, `open`, `close` and `stop`
are rejected until their USB frames have been captured. The fixed transmit fields
come from the supplied reference and were verified only for that installation.

The service subscribes at QoS 0 and rejects retained deliveries to avoid executing
old commands on reconnect. Publish commands with retain disabled. Event topics
remain retained; their latest event is not a confirmed actuator state.
Commands received while USB is unavailable or the bounded queue is full are
rejected. USB failures are not retried for commands: delivery may be uncertain.
Commands also wait while an outgoing event awaits broker acknowledgement.
After a successful write, the service listens for up to three seconds for a
radio acknowledgement (`0x01`) from the target receiver to the source address
in the transmitted command. It logs either `Radio acknowledgement received` or
a confirmation warning on timeout, disconnect or shutdown. The next queued
command is sent after that wait completes; ordinary received events continue
to be published. Commands are never automatically resent.

An acknowledgement confirms an observed radio response, not the physical output
state or ON/OFF value. Matching uses the two device addresses: sequence matching
has not been established from captures, so unrelated or delayed acknowledgements
between the same addresses can be mistaken for the pending command's response.
The wait is checked by the service loop; an outstanding MQTT publish can delay
reading a reply or reporting the timeout. A successful USB write alone does not
confirm radio delivery or actuator state.
Restrict broker publish access to the command topic to trusted controllers.

## Code and functions

| File | Main functions and responsibilities |
| --- | --- |
| `mqtt_service.py` | `main()` loads configuration, starts MQTT, handles signals, reads USB reports, publishes JSON and retries USB failures |
| `mqtt_bridge.py` | `load_devices()` reads device names/types; `event_from_report()` validates radio frames and creates payloads |
| `serial_reader.py` | `Reader` manages serial framing, reception probes and on/off transmission |
| `linux_reader.py` | `Reader` validates USB identity; `enable_reception()`, `read()` and `close()` manage Linux hidraw access |
| `protocol.py` | `decode()` extracts IDs, message type, battery information, RSSI, reception quality, data point and raw bytes |
| `app.py` | Windows GUI, device labels and timestamped CSV recordings |
| `hid_reader.py` | Original Windows HID transport |
| `test_bridge.py` | Synthetic regression tests for actions, button sides, frame validation, CSV names and USB transport |
| `verify_capture.py` | Historical decoder comparison against original MRF exports and USB captures |

Power supply, RSSI and reception quality reuse the decoder values shown by the
Windows monitor; the MQTT bridge translates power supply descriptions into English.

## Verification

Run `python3 -m unittest -v test_bridge test_commands test_serial_reader test_debug_log` for synthetic frame and transport tests.
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
