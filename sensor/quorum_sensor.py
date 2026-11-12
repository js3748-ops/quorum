"""Quorum person-counting sensor.

Reads a webcam or IP-camera stream, counts people with a small YOLO model, smooths the count
with a rolling median, and posts only {"people_count": n} to Quorum every few seconds.

PRIVACY: frames live only in memory for the instant they are processed. They are never written
to disk and never sent over the network. The optional --preview window is drawn locally.
"""

import argparse
import os
import statistics
import sys
import threading
import time
from collections import deque
from pathlib import Path

from quorum_api import SAFE_GAP_SECONDS, ReadingSender, mask_key, round_half_up


HERE = Path(__file__).resolve().parent
SMOOTHING_FRAMES = 5
FPS_REPORT_SECONDS = 5.0
WINDOW_TITLE = "Quorum sensor (local preview only, q to quit)"


def load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(HERE / ".env")


def parse_source(value: str):
    value = str(value).strip()
    return int(value) if value.isdigit() else value


def parse_args(argv=None) -> argparse.Namespace:
    load_env()
    parser = argparse.ArgumentParser(description="Count people with a camera and report counts to Quorum.")
    parser.add_argument("--url", default=os.getenv("QUORUM_URL", "http://127.0.0.1:8000"),
                        help="Quorum backend URL (env QUORUM_URL)")
    parser.add_argument("--key", default=os.getenv("SENSOR_KEY", ""),
                        help="Sensor API key from Quorum (env SENSOR_KEY)")
    parser.add_argument("--source", default=os.getenv("VIDEO_SOURCE", "0"),
                        help="Webcam index such as 0, or a stream URL (env VIDEO_SOURCE)")
    parser.add_argument("--interval", type=float, default=float(os.getenv("INTERVAL_SECONDS", "5")),
                        help="Seconds between readings sent to Quorum (env INTERVAL_SECONDS)")
    parser.add_argument("--confidence", type=float, default=float(os.getenv("CONFIDENCE", "0.5")),
                        help="Minimum detection confidence, 0 to 1 (env CONFIDENCE)")
    parser.add_argument("--model", default=os.getenv("MODEL", "yolo11n.pt"),
                        help="Ultralytics model name or path (env MODEL)")
    parser.add_argument("--preview", action="store_true",
                        help="Show a local window with boxes and the count. Press q to quit.")
    args = parser.parse_args(argv)

    if not args.key or "." not in args.key:
        parser.error("SENSOR_KEY is missing or malformed. Set it in sensor/.env or pass --key.")
    if not 0.0 < args.confidence <= 1.0:
        parser.error("CONFIDENCE must be between 0 and 1.")
    if args.interval < SAFE_GAP_SECONDS:
        print(f"INTERVAL_SECONDS={args.interval} is below Quorum's 2-second limit; using {SAFE_GAP_SECONDS}s.")
        args.interval = SAFE_GAP_SECONDS
    args.source = parse_source(args.source)
    return args


class CountReporter(threading.Thread):
    """Posts the latest smoothed count on a schedule, in the background, so a slow or
    unreachable server never stalls the camera loop."""

    def __init__(self, sender: ReadingSender):
        super().__init__(name="quorum-reporter", daemon=True)
        self.sender = sender
        self._lock = threading.Lock()
        self._latest: int | None = None
        self._stop_event = threading.Event()

    def update(self, count: int) -> None:
        with self._lock:
            self._latest = count

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        self.sender.delay_start(self.sender.interval)  # first reading after one interval of counts
        while not self._stop_event.is_set():
            if self._stop_event.wait(min(self.sender.seconds_until_due(), 0.5)):
                break
            if not self.sender.due():
                continue
            with self._lock:
                count = self._latest
            if count is None:
                self.sender.delay_start(0.5)
                continue
            try:
                self.sender.send(count)
            except Exception as error:  # belt and braces: the reporter must never die
                print(f"Unexpected error while sending: {error}. Retrying shortly.")
                self.sender.delay_start(5)


def open_capture(cv2, source):
    capture = cv2.VideoCapture(source)
    if capture.isOpened():
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # keep latency low on network streams
    return capture


def describe_source(source) -> str:
    if isinstance(source, int):
        return f"webcam {source}"
    if "@" in source:  # hide credentials embedded in stream URLs
        scheme, _, rest = source.partition("://")
        return f"{scheme}://***@{rest.split('@', 1)[1]}"
    return source


def main(argv=None) -> int:
    args = parse_args(argv)

    try:
        import cv2
        from ultralytics import YOLO
    except ImportError as error:
        print(f"Missing dependency ({error.name}). Install with: pip install -r sensor/requirements.txt")
        return 1

    try:  # Opt out of Ultralytics usage analytics. Frames were never part of them, but send nothing.
        from ultralytics import settings
        settings.update({"sync": False})
    except Exception:
        pass

    print(f"Loading model {args.model} (downloads once on first run)...")
    try:
        model = YOLO(args.model)
    except Exception as error:
        print(f"Could not load model {args.model}: {error}")
        return 1
    person_ids = [index for index, name in model.names.items() if name == "person"]
    if not person_ids:
        print(f"Model {args.model} has no 'person' class.")
        return 1

    sender = ReadingSender(args.url, args.key, args.interval, label="camera")
    reporter = CountReporter(sender)
    print(
        f"Quorum sensor: {args.url} | key {mask_key(args.key)} | source {describe_source(args.source)} | "
        f"every {sender.interval:g}s | confidence >= {args.confidence:g}"
    )
    print("Frames stay in memory on this device. Only the people count is sent.")

    capture = open_capture(cv2, args.source)
    reopen_delay = 1.0
    recent_counts: deque[int] = deque(maxlen=SMOOTHING_FRAMES)
    frames = 0
    fps_started = time.monotonic()
    smoothed = 0
    reporter.start()

    try:
        while True:
            ok, frame = capture.read() if capture.isOpened() else (False, None)
            if not ok or frame is None:
                print(f"Cannot read from {describe_source(args.source)}; retrying in {reopen_delay:.0f}s.")
                capture.release()
                time.sleep(reopen_delay)
                reopen_delay = min(reopen_delay * 2, 30.0)
                capture = open_capture(cv2, args.source)
                continue
            reopen_delay = 1.0

            result = model.predict(frame, classes=person_ids, conf=args.confidence, verbose=False)[0]
            raw_count = len(result.boxes)
            recent_counts.append(raw_count)
            smoothed = round_half_up(statistics.median(recent_counts))
            reporter.update(smoothed)

            frames += 1
            elapsed = time.monotonic() - fps_started
            if elapsed >= FPS_REPORT_SECONDS:
                print(f"FPS {frames / elapsed:.1f} | detected {raw_count} | smoothed {smoothed}")
                frames = 0
                fps_started = time.monotonic()

            if args.preview:
                for box in result.boxes.xyxy.tolist():
                    x1, y1, x2, y2 = (int(value) for value in box)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (60, 180, 60), 2)
                cv2.putText(frame, f"People: {smoothed}", (12, 36), cv2.FONT_HERSHEY_SIMPLEX,
                            1.0, (40, 40, 200), 2, cv2.LINE_AA)
                cv2.imshow(WINDOW_TITLE, frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
            # The frame is dropped here and overwritten by the next read. It is never saved or sent.
    except KeyboardInterrupt:
        pass
    finally:
        reporter.stop()
        capture.release()
        if args.preview:
            cv2.destroyAllWindows()
        print(f"Stopped. Readings accepted by Quorum: {sender.sent}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
