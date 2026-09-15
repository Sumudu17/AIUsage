"""
AI Usage - single entry point.

Runs both halves of the app in one process:

  * the background monitor, on a daemon thread
  * the desktop card, on the main thread (Tk requires that)

This is what the packaged AIUsage.exe runs, and it behaves the same as
START.bat did with two separate processes.  The monitor still serves its
local push server, so the widget receives updates exactly as before and a
second widget could still connect to it.

Run from source with:   py app.py
"""

from __future__ import annotations

import os
import sys
import threading

# When frozen by PyInstaller the code is unpacked to a temp folder, so config/
# and data/ are kept beside the .exe.  From source they sit beside this file.
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, BASE_DIR)

from usage_service import monitor as monitor_module   # noqa: E402
from usage_service import providers as providers_module  # noqa: E402
from widget import widget as widget_module            # noqa: E402


_INSTANCE_LOCK = None  # kept alive for the life of the process


def already_running():
    """True when another copy of the app is already running.

    START.bat was safe to click twice; without this, double-clicking the exe
    would put a second card on the screen.  A named mutex is the standard
    Windows way to ask, and it needs nothing outside the standard library.
    """
    global _INSTANCE_LOCK
    if os.name != "nt":
        return False
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.CreateMutexW(None, False, "AIUsageWidget.SingleInstance")
        if not handle:
            return False
        ERROR_ALREADY_EXISTS = 183
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            return True
        _INSTANCE_LOCK = handle
    except Exception:
        return False   # never block startup over this
    return False


def ensure_config():
    """On first run, drop an editable config.json next to the executable.

    The app works without it (the defaults are built in), but a packaged user
    would otherwise have no file to edit.  An existing config is never
    touched.
    """
    target = os.path.join(BASE_DIR, "config", "config.json")
    if os.path.exists(target):
        return

    # The example ships inside the exe; from source it sits in config/.
    bundled = os.path.join(getattr(sys, "_MEIPASS", BASE_DIR),
                           "config", "config.example.json")
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(bundled, "r", encoding="utf-8-sig") as src:
            text = src.read()
        with open(target, "w", encoding="utf-8") as dst:
            dst.write(text)
    except OSError:
        pass  # not fatal - built-in defaults still apply


def start_monitor(stop_event):
    """Run the collect/push loop on a daemon thread."""
    config = monitor_module.load_config()
    interval = config.get("refresh_minutes", 10)
    provider_list = providers_module.build_providers(config)

    def loop():
        try:
            monitor_module.serve_forever(config, interval, provider_list,
                                         stop_event=stop_event)
        except Exception as exc:                    # keep the card alive
            monitor_module.log(
                "[monitor] stopped unexpectedly: {}: {}".format(
                    type(exc).__name__, exc))

    thread = threading.Thread(target=loop, name="monitor", daemon=True)
    thread.start()
    return thread


def main():
    # Without a console (the packaged app is windowed) anything written to
    # stdout is discarded, so send the monitor's output to a log file.
    monitor_module.LOG_FILE = os.path.join(BASE_DIR, "data", "monitor.log")
    try:
        os.makedirs(os.path.dirname(monitor_module.LOG_FILE), exist_ok=True)
    except OSError:
        pass

    if already_running():
        return          # a card is already on screen; do not open a second

    ensure_config()

    stop_event = threading.Event()
    start_monitor(stop_event)

    # The widget owns the main thread and blocks here until it is closed.
    try:
        widget_module.UsageWidget(widget_module.load_config()).run()
    finally:
        stop_event.set()


if __name__ == "__main__":
    main()
