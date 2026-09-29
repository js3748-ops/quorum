import sys
import time
import webbrowser

from dev import (
    FRONTEND_PORT,
    HOST,
    configure_stop_signals,
    port_is_available,
    print_busy_port,
    start_process,
    stop_process,
)


def main() -> int:
    configure_stop_signals()
    if not port_is_available(FRONTEND_PORT):
        print_busy_port(FRONTEND_PORT, "frontend")
        return 1

    print(
        "Quorum frontend\n"
        "  Open:  http://127.0.0.1:5500",
        flush=True,
    )
    print("http://127.0.0.1:5500", flush=True)
    process = start_process(
        [
            sys.executable,
            "-m",
            "http.server",
            str(FRONTEND_PORT),
            "--bind",
            HOST,
            "--directory",
            "frontend",
        ]
    )
    webbrowser.open("http://127.0.0.1:5500")
    try:
        while process.poll() is None:
            time.sleep(0.25)
        print(
            f"Quorum frontend stopped unexpectedly with exit code {process.returncode}.",
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
