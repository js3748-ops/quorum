import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


HOST = "127.0.0.1"
BACKEND_PORT = 8000
FRONTEND_PORT = 5500
ROOT = Path(__file__).resolve().parent


def port_is_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((HOST, port))
        except OSError:
            return False
    return True


def start_process(command: list[str]) -> subprocess.Popen:
    options: dict[str, object] = {"cwd": ROOT}
    if os.name != "nt":
        options["start_new_session"] = True
    return subprocess.Popen(command, **options)


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            process.wait(timeout=3)
            return
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=2)
                return
            except subprocess.TimeoutExpired:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                return
    try:
        os.killpg(process.pid, signal.SIGINT)
        process.wait(timeout=5)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def handle_stop_signal(_signum, _frame) -> None:
    raise KeyboardInterrupt


def configure_stop_signals() -> None:
    signal.signal(signal.SIGTERM, handle_stop_signal)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, handle_stop_signal)


def print_busy_port(port: int, name: str) -> None:
    print(
        f"Cannot start Quorum {name}: port {port} is already in use.\n"
        f"  Find the process: netstat -ano | findstr :{port}\n"
        "  Stop it: taskkill /PID <pid> /F",
        file=sys.stderr,
        flush=True,
    )


def main() -> int:
    configure_stop_signals()

    ports = ((BACKEND_PORT, "backend"), (FRONTEND_PORT, "frontend"))
    busy = [(port, name) for port, name in ports if not port_is_available(port)]
    if busy:
        for port, name in busy:
            print_busy_port(port, name)
        return 1

    processes: list[subprocess.Popen] = []
    try:
        print(
            "Quorum is running\n"
            "  Frontend:  http://127.0.0.1:5500\n"
            "  Backend:   http://127.0.0.1:8000\n"
            "  API docs:  http://127.0.0.1:8000/docs",
            flush=True,
        )
        processes.append(
            start_process(
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
        )
        processes.append(
            start_process(
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
        )

        while all(process.poll() is None for process in processes):
            time.sleep(0.25)

        failed = next(process for process in processes if process.poll() is not None)
        print(
            f"A Quorum server stopped unexpectedly with exit code {failed.returncode}.",
            file=sys.stderr,
        )
        return failed.returncode or 1
    except KeyboardInterrupt:
        return 0
    finally:
        for process in reversed(processes):
            stop_process(process)


if __name__ == "__main__":
    raise SystemExit(main())
