"""
AI Usage desktop widget.

A small always-on-top card that shows the usage the background monitor
collects.  It does no usage checking of its own - it connects to the
monitor's local push server and renders whatever arrives, falling back to
data/usage.json when the monitor is not running.

Run it with:      py widget\\widget.py
or double-click:  run-widget.bat
"""

from __future__ import annotations

import json
import os
import queue
import socket
import sys
import threading
import tkinter as tk
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)

CONFIG_FILE = os.path.join(BASE_DIR, "config", "config.json")
DATA_FILE = os.path.join(BASE_DIR, "data", "usage.json")

LOCAL_TZ = datetime.now().astimezone().tzinfo

# --------------------------------------------------------------------------
# Theme
# --------------------------------------------------------------------------
COLOR_BORDER = "#2b303b"
COLOR_BG = "#14161c"
COLOR_LABEL = "#8b93a7"
COLOR_MUTED = "#666e82"
COLOR_VALUE = "#eef1f7"
COLOR_TITLE = "#c9d1e3"
COLOR_TRACK = "#232733"

COLOR_OK = "#25d366"       # green  - connected, data current
COLOR_WARN = "#f5a623"     # yellow - cached / stale data
COLOR_BAD = "#ff4d4f"      # red    - monitor unavailable

FONT_TITLE = ("Segoe UI Semibold", 9)
FONT_PROVIDER = ("Segoe UI Semibold", 9)
FONT_LABEL = ("Segoe UI", 9)
FONT_VALUE = ("Segoe UI Semibold", 9)
FONT_SMALL = ("Segoe UI", 8)
FONT_CLOSE = ("Segoe UI", 9)

CARD_WIDTH = 260
BAR_HEIGHT = 4
SCREEN_MARGIN = 12

DEFAULT_WIDGET_CONFIG = {
    "x": None,
    "y": None,
    "opacity": 0.96,
    "stale_after_minutes": 30,
}


# --------------------------------------------------------------------------
# config / cache
# --------------------------------------------------------------------------
def load_config():
    config = {"server": {"host": "127.0.0.1", "port": 45654},
              "refresh_minutes": 10,
              "widget": dict(DEFAULT_WIDGET_CONFIG)}
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


def save_widget_position(x, y):
    """Write only the widget x/y back into config.json, leaving the rest."""
    try:
        # utf-8-sig: tolerate a BOM, which Notepad and PowerShell both add.
        with open(CONFIG_FILE, "r", encoding="utf-8-sig") as fh:
            stored = json.load(fh)
        if not isinstance(stored, dict):
            stored = {}
    except OSError:
        stored = {}          # no config file yet - fine, create one
    except ValueError:
        # The file exists but is not valid JSON.  Saving now would replace
        # the user's settings with just a position, so leave it alone.
        return

    widget = stored.get("widget")
    if not isinstance(widget, dict):
        widget = {}
    widget["x"] = x
    widget["y"] = y
    stored["widget"] = widget

    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(stored, fh, indent=2)
        os.replace(tmp, CONFIG_FILE)
    except OSError:
        pass


def read_cached_snapshot():
    """The monitor's last written snapshot, or None."""
    try:
        with open(DATA_FILE, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------
# formatting
# --------------------------------------------------------------------------
def parse_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=LOCAL_TZ)


def format_clock(dt):
    """'2:50 AM' without a leading zero (%-I is not portable on Windows)."""
    return "{}:{:02d} {}".format((dt.hour % 12) or 12, dt.minute,
                                 "AM" if dt.hour < 12 else "PM")


def format_reset(dt, now=None):
    """'Today 2:50 AM' / 'Tomorrow 12:30 PM' / 'Mon 8:00 AM' / 'Sep 20, 5:30 AM'."""
    if dt is None:
        return "--"
    now = now or datetime.now(tz=LOCAL_TZ)
    days = (dt.date() - now.date()).days
    clock = format_clock(dt)
    if days == 0:
        return "Today {}".format(clock)
    if days == 1:
        return "Tomorrow {}".format(clock)
    if 2 <= days <= 6:
        return "{} {}".format(dt.strftime("%a"), clock)
    if days < 0:
        return "{} (passed)".format(clock)
    return "{} {}, {}".format(dt.strftime("%b"), dt.day, clock)


def format_remaining(dt, now=None):
    """'3h 25m' / '4d 8h' / '12m' / 'due'."""
    if dt is None:
        return ""
    now = now or datetime.now(tz=LOCAL_TZ)
    seconds = int((dt - now).total_seconds())
    if seconds <= 0:
        return "due"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return "{}d {}h".format(days, hours)
    if hours:
        return "{}h {}m".format(hours, minutes)
    return "{}m".format(max(1, minutes))


def format_age(dt, now=None):
    if dt is None:
        return "unknown"
    now = now or datetime.now(tz=LOCAL_TZ)
    seconds = int((now - dt).total_seconds())
    if seconds < 90:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return "{}m ago".format(minutes)
    hours = minutes // 60
    if hours < 24:
        return "{}h ago".format(hours)
    return "{}d ago".format(hours // 24)


def bar_color(percent):
    if percent is None:
        return COLOR_TRACK
    if percent >= 90:
        return COLOR_BAD
    if percent >= 70:
        return COLOR_WARN
    return COLOR_OK


WINDOW_ORDER = {"session": 0, "daily": 1, "weekly": 2}


def sorted_windows(windows):
    """Session first, then daily, then weekly, then anything else."""
    def rank(item):
        key = item[0].split("_")[0]
        return (WINDOW_ORDER.get(key, 9), item[0])
    return sorted(windows.items(), key=rank)


# ==========================================================================
# monitor client (background thread, never touches Tk directly)
# ==========================================================================
class MonitorClient:
    """Keeps a connection to the monitor and posts events onto a queue."""

    def __init__(self, host, port, events):
        self.host = host
        self.port = port
        self.events = events
        self._stop = threading.Event()
        self._sock = None
        self._lock = threading.Lock()

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._stop.set()
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except OSError:
                    pass

    def send_command(self, command):
        """Ask the monitor to do something (currently just 'refresh')."""
        with self._lock:
            sock = self._sock
        if not sock:
            return False
        try:
            sock.sendall((json.dumps({"command": command}) + "\n").encode())
            return True
        except OSError:
            return False

    def _loop(self):
        while not self._stop.is_set():
            try:
                sock = socket.create_connection((self.host, self.port),
                                                timeout=4)
            except OSError:
                self.events.put(("disconnected", None))
                self._stop.wait(3)       # retry shortly
                continue

            with self._lock:
                self._sock = sock
            self.events.put(("connected", None))

            buffer = b""
            try:
                sock.settimeout(None)
                while not self._stop.is_set():
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            snapshot = json.loads(line.decode("utf-8"))
                        except ValueError:
                            continue
                        self.events.put(("snapshot", snapshot))
            except OSError:
                pass
            finally:
                with self._lock:
                    self._sock = None
                try:
                    sock.close()
                except OSError:
                    pass
                self.events.put(("disconnected", None))
                self._stop.wait(3)


# ==========================================================================
# the card
# ==========================================================================
class UsageWidget:
    def __init__(self, config):
        self.config = config
        self.widget_config = config.get("widget", dict(DEFAULT_WIDGET_CONFIG))
        self.refresh_minutes = float(config.get("refresh_minutes", 10))
        self.stale_after = float(
            self.widget_config.get("stale_after_minutes", 30))

        self.snapshot = None
        self.connected = False
        self.live = False          # True once a snapshot arrived over the socket
        self._drag_offset = (0, 0)
        self._countdowns = []      # (label widget, reset datetime)

        self.events = queue.Queue()
        server = config.get("server", {})
        self.client = MonitorClient(server.get("host", "127.0.0.1"),
                                    int(server.get("port", 45654)),
                                    self.events)

        self.root = tk.Tk()
        self._build_window()
        self._build_shell()

        # Requirement: show the last cached values immediately on start.
        self.snapshot = read_cached_snapshot()
        self.render()
        self._place_window()

    # ----- window chrome ---------------------------------------------------
    def _build_window(self):
        self.root.title("AI Usage")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=COLOR_BORDER)
        self.root.minsize(CARD_WIDTH, 0)   # keep a steady card width
        try:
            self.root.attributes("-alpha",
                                 float(self.widget_config.get("opacity", 0.94)))
        except (tk.TclError, TypeError, ValueError):
            pass
        try:
            self.root.attributes("-toolwindow", True)   # keep out of taskbar
        except tk.TclError:
            pass
        self.root.protocol("WM_DELETE_WINDOW", self.exit_app)

    def _build_shell(self):
        """The parts that never change: header, body container, footer."""
        card = tk.Frame(self.root, bg=COLOR_BG)
        card.pack(padx=1, pady=1, fill="both", expand=True)

        outer = tk.Frame(card, bg=COLOR_BG)
        outer.pack(padx=12, pady=10, fill="both", expand=True)

        header = tk.Frame(outer, bg=COLOR_BG)
        header.pack(fill="x")

        self.status_dot = tk.Canvas(header, width=10, height=10, bg=COLOR_BG,
                                    highlightthickness=0)
        self.status_dot_id = self.status_dot.create_oval(1, 1, 9, 9,
                                                         fill=COLOR_BAD,
                                                         outline="")
        self.status_dot.pack(side="left", padx=(0, 7))

        tk.Label(header, text="AI USAGE", font=FONT_TITLE, fg=COLOR_TITLE,
                 bg=COLOR_BG).pack(side="left")

        self.close_button = tk.Label(header, text="✕", font=FONT_CLOSE,
                                     fg=COLOR_LABEL, bg=COLOR_BG,
                                     cursor="hand2")
        self.close_button.pack(side="right")
        self.close_button.bind(
            "<Enter>", lambda e: self.close_button.config(fg=COLOR_BAD))
        self.close_button.bind(
            "<Leave>", lambda e: self.close_button.config(fg=COLOR_LABEL))

        # Providers are re-created whenever new data arrives.
        self.body = tk.Frame(outer, bg=COLOR_BG)
        self.body.pack(fill="both", expand=True)

        self.footer = tk.Label(outer, text="", font=FONT_SMALL, fg=COLOR_MUTED,
                               bg=COLOR_BG, anchor="w")
        self.footer.pack(fill="x", pady=(8, 0))

        self.menu = tk.Menu(self.root, tearoff=0, bg=COLOR_BG, fg=COLOR_VALUE,
                            activebackground=COLOR_BORDER,
                            activeforeground=COLOR_VALUE, font=FONT_LABEL,
                            borderwidth=0)
        self.menu.add_command(label="Refresh", command=self.request_refresh)
        self.menu.add_command(label="Move to Top Right",
                              command=self.move_to_top_right)
        self.menu.add_separator()
        self.menu.add_command(label="Exit", command=self.exit_app)

    # ----- rendering -------------------------------------------------------
    def render(self):
        """Rebuild the provider rows from the current snapshot."""
        for child in self.body.winfo_children():
            child.destroy()
        self._countdowns = []

        now = datetime.now(tz=LOCAL_TZ)
        providers = (self.snapshot or {}).get("providers") or {}

        if not providers:
            tk.Label(self.body, text="Waiting for data...", font=FONT_LABEL,
                     fg=COLOR_LABEL, bg=COLOR_BG, anchor="w"
                     ).pack(fill="x", pady=(10, 6))
            for name in ("Claude", "Codex"):
                self._render_placeholder(name)
        else:
            for name in ("claude", "codex"):
                if name in providers:
                    self._render_provider(name, providers[name], now)
            for name, data in providers.items():   # anything else configured
                if name not in ("claude", "codex"):
                    self._render_provider(name, data, now)

        self._update_status(now)
        self._bind_events(self.root)

    def _render_placeholder(self, title):
        block = tk.Frame(self.body, bg=COLOR_BG)
        block.pack(fill="x", pady=(6, 0))
        tk.Label(block, text=title.upper(), font=FONT_PROVIDER, fg=COLOR_TITLE,
                 bg=COLOR_BG, anchor="w").pack(fill="x")
        for label in ("Session", "Weekly"):
            row = tk.Frame(block, bg=COLOR_BG)
            row.pack(fill="x")
            tk.Label(row, text=label, font=FONT_LABEL, fg=COLOR_LABEL,
                     bg=COLOR_BG).pack(side="left")
            tk.Label(row, text="--", font=FONT_VALUE, fg=COLOR_MUTED,
                     bg=COLOR_BG).pack(side="right")
            tk.Label(block, text="Resets --", font=FONT_SMALL, fg=COLOR_MUTED,
                     bg=COLOR_BG, anchor="w").pack(fill="x")

    def _render_provider(self, name, data, now):
        block = tk.Frame(self.body, bg=COLOR_BG)
        block.pack(fill="x", pady=(8, 0))

        head = tk.Frame(block, bg=COLOR_BG)
        head.pack(fill="x")
        tk.Label(head, text=name.upper(), font=FONT_PROVIDER, fg=COLOR_TITLE,
                 bg=COLOR_BG).pack(side="left")

        observed = parse_dt(data.get("observed_at"))
        note = ""
        if not data.get("ok") and data.get("error"):
            note = "unavailable"
        elif observed and (now - observed) > timedelta(minutes=self.stale_after):
            # Codex numbers only move when Codex is used, so say how old
            # they are instead of pretending they are current.
            note = format_age(observed, now)
        elif data.get("plan"):
            note = str(data["plan"])
        if note:
            tk.Label(head, text=note, font=FONT_SMALL, fg=COLOR_MUTED,
                     bg=COLOR_BG).pack(side="right")

        windows = data.get("windows") or {}
        if not windows:
            tk.Label(block, text=data.get("error") or "no data",
                     font=FONT_SMALL, fg=COLOR_MUTED, bg=COLOR_BG,
                     anchor="w", wraplength=CARD_WIDTH - 24
                     ).pack(fill="x", pady=(2, 0))
            return

        for _key, window in sorted_windows(windows):
            self._render_window(block, window, now)

    def _render_window(self, parent, window, now):
        percent = window.get("used_percent")
        reset_at = parse_dt(window.get("resets_at"))

        row = tk.Frame(parent, bg=COLOR_BG)
        row.pack(fill="x", pady=(4, 0))
        tk.Label(row, text=window.get("label", "Usage"), font=FONT_LABEL,
                 fg=COLOR_LABEL, bg=COLOR_BG).pack(side="left")
        tk.Label(row, text="--" if percent is None else "{:g}%".format(percent),
                 font=FONT_VALUE,
                 fg=COLOR_VALUE if percent is not None else COLOR_MUTED,
                 bg=COLOR_BG).pack(side="right")

        # usage bar
        # An explicit width matters: a Canvas with none defaults to 378px and
        # would stretch the whole card.  It still fills the row via pack().
        bar = tk.Canvas(parent, height=BAR_HEIGHT, width=CARD_WIDTH - 24,
                        bg=COLOR_TRACK, highlightthickness=0)
        bar.pack(fill="x", pady=(3, 0))
        if percent is not None:
            fraction = max(0.0, min(100.0, float(percent))) / 100.0
            colour = bar_color(percent)

            def paint(_event=None, canvas=bar, frac=fraction, col=colour):
                canvas.delete("fill")
                width = canvas.winfo_width()
                if width > 1:
                    canvas.create_rectangle(0, 0, int(width * frac),
                                            BAR_HEIGHT, fill=col, outline="",
                                            tags="fill")
            bar.bind("<Configure>", paint)
            paint()

        # reset line: "Resets Tomorrow 12:30 PM  ·  12h 18m"
        reset_row = tk.Frame(parent, bg=COLOR_BG)
        reset_row.pack(fill="x", pady=(2, 0))
        tk.Label(reset_row, text="Resets {}".format(format_reset(reset_at, now)),
                 font=FONT_SMALL, fg=COLOR_MUTED, bg=COLOR_BG).pack(side="left")
        countdown = tk.Label(reset_row, text=format_remaining(reset_at, now),
                             font=FONT_SMALL, fg=COLOR_MUTED, bg=COLOR_BG)
        countdown.pack(side="right")
        if reset_at:
            self._countdowns.append((countdown, reset_at))

    def _update_status(self, now=None):
        """Green = live data, yellow = cached/stale, red = no monitor."""
        now = now or datetime.now(tz=LOCAL_TZ)
        last_updated = parse_dt((self.snapshot or {}).get("last_updated"))
        has_data = bool((self.snapshot or {}).get("providers"))

        stale_limit = timedelta(minutes=max(self.refresh_minutes * 2, 5))
        data_is_fresh = bool(last_updated and (now - last_updated) <= stale_limit)

        if self.connected and has_data and data_is_fresh:
            colour, state = COLOR_OK, "live"
        elif has_data:
            colour = COLOR_WARN
            state = "cached data" if not self.connected else "stale data"
        else:
            colour = COLOR_BAD
            state = "monitor offline" if not self.connected else "waiting"

        self.status_dot.itemconfig(self.status_dot_id, fill=colour)

        if last_updated:
            self.footer.config(
                text="Updated {}  ·  {}".format(
                    format_clock(last_updated), state))
        else:
            self.footer.config(text="Waiting for data...  ·  {}".format(state))

    def _tick(self):
        """Keep the countdowns and the status honest between updates."""
        now = datetime.now(tz=LOCAL_TZ)
        for label, reset_at in self._countdowns:
            try:
                label.config(text=format_remaining(reset_at, now))
            except tk.TclError:
                pass  # widget was rebuilt underneath us
        self._update_status(now)
        self.root.after(30000, self._tick)

    # ----- events from the monitor thread ----------------------------------
    def _drain_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "connected":
                    self.connected = True
                    self._update_status()
                elif kind == "disconnected":
                    self.connected = False
                    self.live = False
                    self._update_status()
                elif kind == "snapshot":
                    self.snapshot = payload
                    self.live = True
                    self.render()
        except queue.Empty:
            pass
        self.root.after(250, self._drain_events)

    # ----- mouse -----------------------------------------------------------
    def _bind_events(self, widget):
        widget.bind("<Button-1>", self._start_drag)
        widget.bind("<B1-Motion>", self._do_drag)
        widget.bind("<ButtonRelease-1>", self._end_drag)
        widget.bind("<Button-3>", self._show_menu)
        for child in widget.winfo_children():
            self._bind_events(child)
        if widget is self.root:
            # Bound last so the close button closes instead of dragging.
            self.close_button.bind("<Button-1>", self._close_clicked)

    def _close_clicked(self, _event):
        self.exit_app()
        return "break"

    def _start_drag(self, event):
        self._drag_offset = (event.x_root - self.root.winfo_x(),
                             event.y_root - self.root.winfo_y())

    def _do_drag(self, event):
        self.root.geometry("+{}+{}".format(
            event.x_root - self._drag_offset[0],
            event.y_root - self._drag_offset[1]))

    def _end_drag(self, _event):
        self._store_position()

    def _show_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    # ----- position --------------------------------------------------------
    def _place_window(self):
        self.root.update_idletasks()
        x, y = self.widget_config.get("x"), self.widget_config.get("y")
        if isinstance(x, int) and isinstance(y, int):
            max_x = self.root.winfo_screenwidth() - self.root.winfo_width()
            max_y = self.root.winfo_screenheight() - self.root.winfo_height()
            self._move_to(max(0, min(x, max_x)), max(0, min(y, max_y)))
        else:
            self.move_to_top_right()

    def move_to_top_right(self):
        self.root.update_idletasks()
        self._move_to(
            self.root.winfo_screenwidth() - self.root.winfo_width() - SCREEN_MARGIN,
            SCREEN_MARGIN)

    def _move_to(self, x, y):
        self.root.geometry("+{}+{}".format(x, y))
        self.widget_config["x"] = x
        self.widget_config["y"] = y
        save_widget_position(x, y)

    def _store_position(self):
        # winfo_x/y are only meaningful once the window is actually on screen.
        if self.root.winfo_ismapped():
            self._move_to(self.root.winfo_x(), self.root.winfo_y())

    # ----- actions ---------------------------------------------------------
    def request_refresh(self):
        """Ask the monitor to check now; fall back to re-reading the cache."""
        if not self.client.send_command("refresh"):
            self.snapshot = read_cached_snapshot() or self.snapshot
            self.render()

    def exit_app(self):
        self._store_position()
        self.client.stop()
        self.root.destroy()

    def run(self):
        self.client.start()
        self.root.after(250, self._drain_events)
        self.root.after(30000, self._tick)
        self.root.mainloop()


def main():
    UsageWidget(load_config()).run()


if __name__ == "__main__":
    main()
