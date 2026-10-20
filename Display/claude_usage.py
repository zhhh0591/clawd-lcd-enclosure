"""Today's Claude Code token usage from the local session logs.

Usage:
    python3 claude_usage.py                      # print today's totals once
    python3 claude_usage.py --watch 10           # refresh every 10 s
    python3 claude_usage.py --watch 10 --port auto   # also send to the ESP32 (finds /dev/cu.usbserial-*)

Every assistant reply in ~/.claude/projects/**/*.jsonl carries message.usage. A reply is
logged several times while it streams, so records are keyed by (message.id, requestId)
and only the largest value of each counter is kept.
"""
import argparse
import datetime as dt
import glob
import json
import os
import time

LOG_GLOB = os.path.expanduser("~/.claude/projects/**/*.jsonl")
FIELDS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


class UsageCounter:
    def __init__(self):
        self.day = None
        self.offsets = {}       # file -> bytes already read
        self.replies = {}       # (message.id, requestId) -> {field: tokens}
        self.last_reply = None  # local time of the newest reply today

    def _reset(self, day):
        self.day, self.offsets, self.replies, self.last_reply = day, {}, {}, None

    def _read_new_lines(self, path):
        start = self.offsets.get(path, 0)
        if os.path.getsize(path) < start:       # file was rewritten
            start = 0
        with open(path, "rb") as fh:
            fh.seek(start)
            data = fh.read()
        end = data.rfind(b"\n") + 1             # leave a half-written last line for next time
        self.offsets[path] = start + end
        return data[:end].decode("utf-8", errors="ignore").splitlines()

    def update(self):
        today = dt.date.today()
        if today != self.day:
            self._reset(today)
        midnight = dt.datetime.combine(today, dt.time()).timestamp()
        for path in glob.glob(LOG_GLOB, recursive=True):
            if os.path.getmtime(path) < midnight:
                continue
            for line in self._read_new_lines(path):
                if '"usage"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                msg = rec.get("message")
                if not isinstance(msg, dict) or not msg.get("usage") or not rec.get("timestamp"):
                    continue
                when = dt.datetime.fromisoformat(rec["timestamp"].replace("Z", "+00:00")).astimezone()
                if when.date() != today:
                    continue
                if self.last_reply is None or when > self.last_reply:
                    self.last_reply = when
                key = (msg.get("id"), rec.get("requestId"))
                seen = self.replies.setdefault(key, dict.fromkeys(FIELDS, 0))
                for f in FIELDS:
                    seen[f] = max(seen[f], int(msg["usage"].get(f) or 0))
        return self.totals()

    def totals(self):
        t = dict.fromkeys(FIELDS, 0)
        for r in self.replies.values():
            for f in FIELDS:
                t[f] += r[f]
        t["total"] = sum(t[f] for f in FIELDS)
        t["replies"] = len(self.replies)
        t["last_reply"] = self.last_reply
        return t


def local_epoch(when):
    """Seconds since 1970 on the local wall clock, so the ESP32 needs no time zone."""
    return int(when.timestamp() + when.utcoffset().total_seconds())


def stats_line(t):
    """STATS:<total>,<output>,<replies>,<now>,<last reply>  (times as local epoch, 0 = none yet)"""
    now = local_epoch(dt.datetime.now().astimezone())
    last = local_epoch(t["last_reply"]) if t["last_reply"] else 0
    return f"STATS:{t['total']},{t['output_tokens']},{t['replies']},{now},{last}\n"


def show(t):
    return (f"{dt.datetime.now():%H:%M:%S}  total {t['total']:,}  |  output {t['output_tokens']:,}  "
            f"input {t['input_tokens']:,}  cache write {t['cache_creation_input_tokens']:,}  "
            f"cache read {t['cache_read_input_tokens']:,}  |  {t['replies']} replies")


class Display:
    """Serial link to the ESP32 that survives the USB cable being unplugged and plugged back in."""

    def __init__(self, port, baud):
        import serial                           # pyserial
        self.serial, self.port, self.baud, self.link = serial, port, baud, None

    def _find_port(self):
        if self.port != "auto":
            return self.port if os.path.exists(self.port) else None
        found = sorted(glob.glob("/dev/cu.usbserial-*")) + sorted(glob.glob("/dev/cu.usbmodem*"))
        return found[0] if found else None

    def send(self, line):
        if self.link is None:
            port = self._find_port()
            if port is None:
                print("  (display not connected, will keep looking)", flush=True)
                return
            try:
                self.link = self.serial.Serial(port, self.baud, timeout=1)
            except self.serial.SerialException as err:
                print(f"  (could not open {port}: {err})", flush=True)
                return
            print(f"  (connected to {port})", flush=True)
            time.sleep(2)                       # opening the port resets the ESP32
        try:
            self.link.write(line.encode())
        except (self.serial.SerialException, OSError):
            print("  (display unplugged, will reconnect)", flush=True)
            self.link.close()
            self.link = None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--watch", type=float, metavar="SECONDS", help="keep refreshing")
    ap.add_argument("--port", help="serial port of the ESP32, or 'auto'; sends one STATS line per refresh")
    ap.add_argument("--baud", type=int, default=115200)
    args = ap.parse_args()

    display = Display(args.port, args.baud) if args.port else None
    counter = UsageCounter()
    while True:
        t = counter.update()
        print(show(t), flush=True)
        if display:
            display.send(stats_line(t))
        if not args.watch:
            break
        time.sleep(args.watch)


if __name__ == "__main__":
    main()
