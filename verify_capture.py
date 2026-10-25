"""Cross-check the decoder against the original simultaneous capture/export."""

import re
import subprocess
from pathlib import Path

from protocol import decode


root = Path(__file__).parent
tshark = r"C:\Program Files\Wireshark\tshark.exe"


def verify(pcap_name, txt_name, time_filter=None):
    capture = subprocess.check_output(
        [tshark, "-r", str(root / pcap_name), "-Y", "usb.device_address == 13 && usb.endpoint_address == 0x84 && usbhid.data", "-T", "fields", "-e", "usbhid.data"],
        text=True,
    )
    packets = []
    for line in capture.splitlines():
        raw = bytes.fromhex(line)
        if len(raw) > 3 and raw[2] == 3:
            packets.append(decode(raw))
    monitor = (root / txt_name).read_text(encoding="cp1252").splitlines()
    lines = [line for line in monitor if not time_filter or re.search(time_filter, line)]
    assert len(packets) == len(lines), (pcap_name, len(packets), len(lines))
    for index, (packet, line) in enumerate(zip(packets, lines), 1):
        match = re.search(r"\t(\d+) sendet <([^>]+)> an (\d+)(?: \(resend\))?\s+\(([^)]+)\)\t(\d+) %", line)
        assert match, (pcap_name, index, line)
        source, message, destination, battery, quality = match.groups()
        assert packet.source == int(source), (pcap_name, index, "source")
        assert packet.destination == int(destination), (pcap_name, index, "destination")
        assert packet.message.replace(" (Wiederholung)", "").replace("ON", "EIN").replace("OFF", "AUS") == message, (pcap_name, index, "message")
        assert packet.battery == battery.replace("Batterie: ", ""), (pcap_name, index, "battery")
        assert packet.quality == int(quality), (pcap_name, index, "quality", packet.quality, quality)
    return len(packets)


total = verify("eaton-only.pcapng", "Monitor.txt", r"\t08:30:(?:0[2-9]|1[0-2])\t")
total += verify("eaton-start.pcap", "Monitor_nach_start.txt")

# The later export names devices; its first two lines precede the USB capture.
captured = subprocess.check_output(
    [tshark, "-r", str(root / "eaton-monitor-start.pcap"), "-Y", "usb.device_address == 13 && usb.endpoint_address == 0x84 && usbhid.data", "-T", "fields", "-e", "usbhid.data"],
    text=True,
)
named_packets = [decode(bytes.fromhex(line)) for line in captured.splitlines() if line]
named_lines = [line for line in (root / "Monitor_test.txt").read_text(encoding="cp1252").splitlines() if "\t08:47:28\t" in line or "\t08:47:29\t" in line]
assert len(named_packets) == len(named_lines) == 6
names = {533431: "Kellervor StiegeUnten", 4081332: "KG-EG Stiege", 8351568: "Smart Home Controller"}
for packet, line in zip(named_packets, named_lines):
    parts = line.split("\t")
    match = re.search(r"(.+?) sendet <([^>]+)> an (.+)\s+\(([^)]+)\)$", parts[3].strip())
    assert match, line
    source, message, destination, battery = match.groups()
    quality = parts[4].split()[0]
    assert source == names[packet.source]
    assert destination.startswith(names[packet.destination])
    assert message == packet.message.replace("ON", "EIN").replace("OFF", "AUS")
    assert battery.replace("Batterie: ", "") == packet.battery, (battery, packet.battery)
    assert int(quality) == packet.quality
    if packet.destination_dp is not None:
        assert f"DP:{packet.destination_dp}" in destination
total += len(named_packets)
print(f"{total} Telegramme mit MRF-Export abgeglichen.")
