"""
Background monitor.

Every `refresh_minutes` it asks each provider for its current usage, writes
the result to data/usage.json, and pushes it to any connected widget straight
away.

Run it with:      py -m usage_service.monitor
or double-click:  START.bat (starts the widget too)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime

# Allow both "py -m usage_service.monitor" and "py usage_service\monitor.py".
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from usage_service import providers as providers_module  # noqa: E402
from usage_service.server import PushServer              # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(BASE_DIR, "config", "config.json")
DATA_FILE = os.path.join(BASE_DIR, "data", "usage.json")

LOG_FILE = None  # set by --log; used when running without a console


def log(message):
    """Print to the console and, when --log is used, append to a file.

    Needed because the windowless launcher runs under pythonw.exe, which has
    nowhere to print.
    """
    line = "{} {}".format(datetime.now().strftime("%H:%M:%S"), message)
    try:
        print(line, flush=True)
    except (OSError, ValueError):
        pass  # no console attached (pythonw)
    if LOG_FILE:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


DEFAULT_CONFIG = {
    "refresh_minutes": 10,
    "server": {"host": "127.0.0.1", "port": 45654},
    "providers": {
        "claude": {"enabled": True, "command": "claude", "timeout_seconds": 180},
        "codex": {"enabled": True},
    },
}


# --------------------------------------------------------------------------
def load_config():
    """config/config.json merged over the defaults (missing file is fine)."""
    config = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8-sig") as fh:
            stored = json.load(fh)
    except (OSError, ValueError):
        return config

    if isinstance(stored, dict):
        for key, value in stored.items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                config[key].update(value)
            else:
                config[key] = value
    return config


def read_cache():
    """Last snapshot written to disk, or None."""
    try:
        with open(DATA_FILE, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def write_cache(snapshot):
    """Write the snapshot atomically so a reader never sees half a file."""
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    tmp = DATA_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(snapshot, fh, indent=2)
        os.replace(tmp, DATA_FILE)
    except OSError as exc:
        log("[monitor] could not write cache: {}".format(exc))


# --------------------------------------------------------------------------
def collect(providers, previous=None):
    """Ask every provider for its usage and build one snapshot.

    A provider that fails keeps its previous values (flagged stale) instead of
    blanking the card - nothing is ever reset to zero unless the provider
    itself reports the lower number.
    """
    previous_providers = (previous or {}).get("providers", {})
    result = {}

    for provider in providers:
        try:
            snapshot = provider.fetch()
        except Exception as exc:                      # never kill the loop
            snapshot = {"name": provider.name, "ok": False, "plan": None,
                        "observed_at": None, "windows": {},
                        "error": "{}: {}".format(type(exc).__name__, exc)}

        if not snapshot.get("ok"):
            old = previous_providers.get(provider.name)
            if old and old.get("windows"):
                snapshot["windows"] = old["windows"]
                snapshot["observed_at"] = old.get("observed_at")
                snapshot["plan"] = old.get("plan")
                snapshot["from_cache"] = True

        result[provider.name] = snapshot
        status = "ok" if snapshot.get("ok") else "FAILED: {}".format(
            snapshot.get("error"))
        log("[monitor]   {:<8} {}".format(provider.name, status))

    return {
        "providers": result,
        "last_updated": providers_module.now_local().isoformat(),
    }


def run(argv=None):
    parser = argparse.ArgumentParser(description="AI usage background monitor")
    parser.add_argument("--once", action="store_true",
                        help="collect once, print the result and exit")
    parser.add_argument("--interval", type=float, default=None,
                        help="override the refresh interval, in minutes")
    parser.add_argument("--log", default=None,
                        help="append output to this file (for windowless runs)")
    args = parser.parse_args(argv)

    if args.log:
        global LOG_FILE
        LOG_FILE = args.log if os.path.isabs(args.log) \
            else os.path.join(BASE_DIR, args.log)
        try:
            os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        except OSError:
            pass

    config = load_config()
    interval_minutes = args.interval or config.get("refresh_minutes", 10)
    provider_list = providers_module.build_providers(config)

    if args.once:
        snapshot = collect(provider_list, read_cache())
        write_cache(snapshot)
        print(json.dumps(snapshot, indent=2))
        return 0

    server_cfg = config.get("server", {})

    # Set by a widget asking for an out-of-schedule refresh.
    refresh_requested = threading.Event()

    def on_command(command):
        if command == "refresh":
            log("[monitor] refresh requested by a widget")
            refresh_requested.set()

    server = PushServer(server_cfg.get("host", "127.0.0.1"),
                        int(server_cfg.get("port", 45654)),
                        on_command=on_command)
    try:
        server.start()
    except OSError as exc:
        log("[monitor] cannot listen on {}:{} - {}".format(
            server_cfg.get("host"), server_cfg.get("port"), exc))
        log("[monitor] is another copy of the monitor already running?")
        return 1

    log("[monitor] listening on {}:{}".format(server.host, server.port))
    log("[monitor] refreshing every {} minutes".format(interval_minutes))

    # Push whatever was cached from a previous run right away, so a widget
    # started at the same time is not blank while the first check runs.
    cached = read_cache()
    if cached:
        server.broadcast(cached)

    try:
        while True:
            started = time.time()
            log("[monitor] checking providers...")

            snapshot = collect(provider_list, read_cache())
            write_cache(snapshot)
            server.broadcast(snapshot)
            log("[monitor]   pushed to {} widget(s)".format(
                server.client_count))

            # Sleep until the next slot, but wake early if a widget asks for
            # a refresh.
            elapsed = time.time() - started
            refresh_requested.clear()
            refresh_requested.wait(max(5.0, interval_minutes * 60 - elapsed))
    except KeyboardInterrupt:
        print("\n[monitor] stopping")
    finally:
        server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(run())
