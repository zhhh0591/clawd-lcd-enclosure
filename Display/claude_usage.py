"""Today's Claude Code token usage from the local session logs.

Usage:
    python3 claude_usage.py                      # print today's totals once
    python3 claude_usage.py --watch 10           # refresh every 10 s
    python3 claude_usage.py --watch 10 --port /dev/cu.usbserial-110   # also send to the ESP32

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

    def _reset(self, day):
        self.day, self.offsets, self.replies = day, {}, {}

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
        return t


def show(t):
    return (f"{dt.datetime.now():%H:%M:%S}  total {t['total']:,}  |  output {t['output_tokens']:,}  "
            f"input {t['input_tokens']:,}  cache write {t['cache_creation_input_tokens']:,}  "
            f"cache read {t['cache_read_input_tokens']:,}  |  {t['replies']} replies")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--watch", type=float, metavar="SECONDS", help="keep refreshing")
    ap.add_argument("--port", help="serial port of the ESP32; sends 'TOKENS:<total>' lines")
    ap.add_argument("--baud", type=int, default=115200)
    args = ap.parse_args()

    link = None
    if args.port:
        import serial                           # pyserial
        link = serial.Serial(args.port, args.baud, timeout=1)
        time.sleep(2)                           # opening the port resets the ESP32

    counter = UsageCounter()
    while True:
        t = counter.update()
        print(show(t), flush=True)
        if link:
            link.write(f"TOKENS:{t['total']}\n".encode())
        if not args.watch:
            break
        time.sleep(args.watch)


if __name__ == "__main__":
    main()
