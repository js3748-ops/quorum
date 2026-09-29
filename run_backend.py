import sys
import time

from dev import (
    BACKEND_PORT,
    HOST,
    configure_stop_signals,
    port_is_available,
    print_busy_port,
    start_process,
    stop_process,
)


def main() -> int:
    configure_stop_signals()
    if not port_is_available(BACKEND_PORT):
        print_busy_port(BACKEND_PORT, "backend")
        return 1

    print(
        "Quorum backend\n"
        "  API:       http://127.0.0.1:8000\n"
        "  API docs:  http://127.0.0.1:8000/docs",
        flush=True,
    )
    print("http://127.0.0.1:8000/docs", flush=True)
    process = start_process(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.main:app",
            "--host",
            HOST,
            "--port",
            str(BACKEND_PORT),
            "--reload",
        ]
    )
    try:
        while process.poll() is None:
            time.sleep(0.25)
        print(
            f"Quorum backend stopped unexpectedly with exit code {process.returncode}.",
            file=sys.stderr,
            flush=True,
        )
        return process.returncode or 1
    except KeyboardInterrupt:
        return 0
    finally:
        stop_process(process)


if __name__ == "__main__":
    raise SystemExit(main())
