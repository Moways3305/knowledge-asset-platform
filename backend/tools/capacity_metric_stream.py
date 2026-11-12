"""Bounded delta batches for disposable capacity measurements, never app data."""

import json
from collections import defaultdict, deque


class MetricBuffer:
    def __init__(self, limit=20000, *, started=0):
        self.limit = limit
        self.started = started
        self.samples = defaultdict(lambda: deque(maxlen=limit))
        self.dropped = {}

    def add(self, key, value, stamp):
        rows = self.samples[key]
        if len(rows) == self.limit:
            lost = rows[0][0]
            bounds = self.dropped.setdefault(key, {"count": 0, "first": lost, "last": lost})
            bounds["count"] += 1
            bounds["last"] = lost
        rows.append((stamp, value))

    def drain(self, through):
        # Called on the recording event loop, without an intervening await. The
        # writer thread owns only detached lists, never the live deques.
        frame = {
            "started": self.started,
            "through": through,
            "samples": {key: list(rows) for key, rows in self.samples.items()},
            "dropped": self.dropped,
        }
        self.samples.clear()
        self.dropped = {}
        return frame


def append_frame(path, frame):
    # One writer per unique process incarnation. Readers ignore an unfinished
    # final line and wait for its watermark; a malformed complete line is fatal.
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(frame, separators=(",", ":")) + "\n")


def read_window(directory, start, end, *, expected_writers=1):
    values = defaultdict(list)
    dropped = 0
    writers = {}
    for path in directory.glob("api-metrics-*.jsonl"):
        through = None
        with path.open(encoding="utf-8") as source:
            for line in source:
                if not line.endswith("\n"):
                    break
                frame = json.loads(line)
                through = frame["through"]
                for key, rows in frame["samples"].items():
                    values[key].extend(value for stamp, value in rows if start <= stamp <= end)
                for loss in frame["dropped"].values():
                    if loss["last"] >= start and loss["first"] <= end:
                        dropped += loss["count"]
        # Old stopped workers from prior runs have no watermark in this window.
        if through is not None and through >= start:
            writers[path.name] = (frame["started"], through)
    complete = len(writers) >= expected_writers and all(
        began <= start and through >= end for began, through in writers.values()
    )
    return dict(values), {"complete": complete, "dropped": dropped, "writers": len(writers)}
