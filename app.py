"""Standalone, read-only Eaton CKOZ-00/13 RF monitor for Windows."""

import csv
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from hid_reader import Reader
from protocol import decode

MAX_VISIBLE_ROWS = 5000


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Eaton Funkmonitor")
        self.root.geometry("1120x600")
        self.events = queue.Queue()
        self.reader = None
        self.running = False
        self.csv_file = None
        self.csv_writer = None
        self.counter = 0
        self.names = self.load_names()

        bar = ttk.Frame(root, padding=8)
        bar.pack(fill="x")
        self.start_button = ttk.Button(bar, text="Aufzeichnung starten", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(bar, text="Stoppen", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=8)
        self.status = tk.StringVar(value="Bereit. Bitte MRF vor dem Start schließen.")
        ttk.Label(bar, textvariable=self.status).pack(side="left", padx=12)

        columns = ("time", "source", "destination", "message", "battery", "quality", "rssi", "raw")
        self.tree = ttk.Treeview(root, columns=columns, show="headings")
        headings = ("Zeit", "Absender", "Empfänger", "Meldung", "Versorgung", "Empfang", "RSSI", "Rohdaten")
        widths = (115, 200, 200, 165, 110, 80, 80, 550)
        for column, heading, width in zip(columns, headings, widths):
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=width, minwidth=65, stretch=(column == "raw"))
        self.tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 8))
        scrollbar = ttk.Scrollbar(root, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y", pady=(0, 8))
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.root.after(100, self.process_events)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    @staticmethod
    def load_names():
        path = Path(__file__).resolve().parent / "smarthome_devices.csv"
        if not path.exists():
            return {}
        with path.open(newline="", encoding="utf-8-sig") as source:
            names = {}
            for row in csv.DictReader(source):
                serial = (row.get("Seriennummer") or "").strip()
                name = (row.get("Gerätename") or "").strip()
                if serial.isdecimal() and name:
                    names[int(serial)] = name
            return names

    def device_label(self, device_id, data_point=None):
        if device_id is None:
            return ""
        name = self.names.get(device_id)
        if not name:
            return str(device_id)
        if data_point is not None and name == "Smart Home Controller":
            name += f" (DP: {data_point})"
        return f"{name} [{device_id}]"

    def start(self):
        self.names = self.load_names()
        try:
            reader = Reader()
            reader.enable_reception()
        except Exception as exc:
            if "reader" in locals():
                reader.close()
            messagebox.showerror("Stick nicht verfügbar", str(exc))
            return
        try:
            name = "eaton-monitor-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".csv"
            path = Path(__file__).resolve().parent / name
            self.csv_file = path.open("w", newline="", encoding="utf-8-sig")
            self.csv_writer = csv.writer(self.csv_file, delimiter=";")
            self.csv_writer.writerow(["Zeit", "Absender", "Empfänger", "Meldung", "Versorgung", "Empfang %", "RSSI dBm", "Rohdaten"])
            self.csv_file.flush()
        except Exception as exc:
            reader.close()
            messagebox.showerror("Datei konnte nicht erstellt werden", str(exc))
            return
        self.reader = reader
        self.running = True
        self.counter = 0
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status.set("Aufzeichnung läuft · " + str(path))
        threading.Thread(target=self.read_loop, args=(reader,), daemon=True).start()

    def read_loop(self, reader):
        try:
            while self.running:
                report = reader.read()
                is_radio = len(report) > 3 and report[0] == 0x5A and report[2] == 3
                is_radio |= len(report) > 4 and report[1] == 0x5A and report[3] == 3
                if self.running and is_radio:
                    self.events.put((datetime.now(), decode(report)))
        except Exception as exc:
            if self.running:
                self.events.put(("error", str(exc)))
        finally:
            reader.close()

    def process_events(self):
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            if event[0] == "error":
                self.stop()
                messagebox.showerror("USB-Verbindung unterbrochen", event[1])
                continue
            if not self.running:
                continue
            when, telegram = event
            row = [
                when.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                self.device_label(telegram.source),
                self.device_label(telegram.destination, telegram.destination_dp),
                telegram.message,
                telegram.battery,
                "" if telegram.quality is None else telegram.quality,
                "" if telegram.rssi_dbm is None else telegram.rssi_dbm,
                telegram.raw,
            ]
            item = self.tree.insert("", "end", values=row)
            self.tree.see(item)
            if len(self.tree.get_children()) > MAX_VISIBLE_ROWS:
                self.tree.delete(self.tree.get_children()[0])
            self.csv_writer.writerow(row)
            self.csv_file.flush()
            self.counter += 1
            self.status.set(f"Aufzeichnung läuft · {self.counter} Telegramme")
        self.root.after(100, self.process_events)

    def stop(self):
        self.running = False
        if self.reader:
            self.reader.close()
            self.reader = None
        if self.csv_file:
            self.csv_file.close()
            self.csv_file = None
            self.csv_writer = None
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.status.set(f"Gestoppt · {self.counter} Telegramme aufgezeichnet")

    def close(self):
        self.stop()
        self.root.destroy()


if __name__ == "__main__":
    window = tk.Tk()
    App(window)
    window.mainloop()
