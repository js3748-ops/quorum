"""Simulate Quorum occupancy sensors for several rooms.

Reads sensor/simulated_sensors.json (see simulated_sensors.example.json) and posts realistic,
noisy people counts for each sensor. Create every sensor used here with "is_simulated": true.
Standard library plus optional python-dotenv; no camera or YOLO needed.
"""

import argparse
import json
import math
import os
import random
import sys
import time
from pathlib import Path

from quorum_api import SAFE_GAP_SECONDS, ReadingSender, mask_key, round_half_up


HERE = Path(__file__).resolve().parent
PATTERNS = {"ghost", "normal", "overcrowded", "fluctuating", "empty"}
FLUCTUATION_PERIOD_SECONDS = 300.0
MAX_COUNT = 1000


class SimulatedRoom:
    def __init__(self, spec: dict, rng: random.Random):
        self.label = spec["label"]
        self.sensor_key = spec["sensor_key"]
        self.pattern = spec["pattern"]
        self.expected = spec["expected"]
        self.capacity = spec.get("capacity")  # optional; used by "overcrowded"
        self.rng = rng
        self.level = float(self.expected)
        self.phase = rng.uniform(0, 2 * math.pi)
        self.started = time.monotonic()

    def next_count(self) -> int:
        rng, expected = self.rng, self.expected
        if self.pattern == "empty":
            value = 0.0
        elif self.pattern == "ghost":  # booked but nobody (or one person) showed up
            value = 1.0 if rng.random() < 0.3 else 0.0
        elif self.pattern == "normal":  # wanders gently around the expected attendance
            self.level += 0.3 * (expected - self.level) + rng.gauss(0, max(0.8, 0.08 * expected))
            value = self.level + rng.gauss(0, 0.5)
        elif self.pattern == "overcrowded":  # clearly above capacity
            limit = self.capacity or expected
            value = max(limit + 1, limit * 1.3 + rng.gauss(0, max(1.0, 0.06 * limit)))
        else:  # fluctuating: people drifting in and out over a few minutes
            elapsed = time.monotonic() - self.started
            wave = math.sin(2 * math.pi * elapsed / FLUCTUATION_PERIOD_SECONDS + self.phase)
            value = expected * (0.6 + 0.5 * wave) + rng.gauss(0, max(1.0, 0.1 * expected))
        return min(MAX_COUNT, max(0, round_half_up(value)))


def load_rooms(path: Path, rng: random.Random) -> list[SimulatedRoom]:
    try:
        specs = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(
            f"{path} not found. Copy simulated_sensors.example.json to simulated_sensors.json and add your keys."
        )
    except json.JSONDecodeError as error:
        raise SystemExit(f"{path} is not valid JSON: {error}")
    if not isinstance(specs, list) or not specs:
        raise SystemExit(f"{path} must contain a non-empty JSON list of sensors.")

    rooms = []
    for index, spec in enumerate(specs, start=1):
        where = f"{path.name} entry {index}"
        if not isinstance(spec, dict):
            raise SystemExit(f"{where} must be an object.")
        missing = [field for field in ("label", "sensor_key", "pattern", "expected") if field not in spec]
        if missing:
            raise SystemExit(f"{where} is missing: {', '.join(missing)}.")
        if spec["pattern"] not in PATTERNS:
            raise SystemExit(f"{where}: pattern must be one of {', '.join(sorted(PATTERNS))}.")
        if not isinstance(spec["expected"], int) or spec["expected"] < 0:
            raise SystemExit(f"{where}: expected must be a whole number of people, 0 or more.")
        capacity = spec.get("capacity")
        if capacity is not None and (not isinstance(capacity, int) or capacity < 1):
            raise SystemExit(f"{where}: capacity, if given, must be a positive whole number.")
        key = str(spec["sensor_key"])
        if "REPLACE" in key.upper() or "." not in key:
            raise SystemExit(f"{where} ({spec['label']}): sensor_key is still a placeholder or malformed.")
        rooms.append(SimulatedRoom(spec, rng))
    return rooms


def main(argv=None) -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv(HERE / ".env")
    except ImportError:
        pass

    parser = argparse.ArgumentParser(description="Post simulated occupancy readings to Quorum.")
    parser.add_argument("--config", type=Path, default=HERE / "simulated_sensors.json",
                        help="Path to the sensors JSON file")
    parser.add_argument("--url", default=os.getenv("QUORUM_URL", "http://127.0.0.1:8000"),
                        help="Quorum backend URL (env QUORUM_URL)")
    parser.add_argument("--interval", type=float, default=float(os.getenv("INTERVAL_SECONDS", "5")),
                        help="Seconds between readings per sensor (env INTERVAL_SECONDS)")
    parser.add_argument("--once", action="store_true", help="Send one reading per sensor, then exit")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for repeatable runs")
    args = parser.parse_args(argv)

    if args.interval < SAFE_GAP_SECONDS:
        print(f"Interval {args.interval}s is below Quorum's 2-second limit; using {SAFE_GAP_SECONDS}s.")
        args.interval = SAFE_GAP_SECONDS

    rng = random.Random(args.seed)
    rooms = load_rooms(args.config, rng)
    senders = []
    for offset, room in enumerate(rooms):
        sender = ReadingSender(args.url, room.sensor_key, args.interval, label=room.label)
        sender.delay_start(offset * 0.3)  # stagger so rooms do not all post at the same instant
        senders.append((room, sender))
        print(f"  {room.label:<24} pattern={room.pattern:<12} expected={room.expected:<4} key {mask_key(room.sensor_key)}")
    print(f"Simulating {len(rooms)} sensor(s) against {args.url} every {args.interval:g}s. Ctrl+C to stop.")

    attempted = set()
    try:
        while True:
            for room, sender in senders:
                if sender.due():
                    sender.send(room.next_count())
                    attempted.add(room.label)
            if args.once and len(attempted) == len(senders):
                break
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    total = sum(sender.sent for _, sender in senders)
    print(f"Stopped. Readings accepted by Quorum: {total}.")
    if args.once and total < len(senders):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
