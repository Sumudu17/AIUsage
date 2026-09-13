"""
Provider adapters: turn whatever Claude and Codex expose locally into one
common shape.

Every provider returns a dict like:

    {
      "ok": True,
      "error": None,
      "plan": "subscription",
      "observed_at": "2026-09-14T00:20:00+05:30",   # when the numbers are from
      "windows": {
        "session": {
          "label": "Session (5h)",
          "used_percent": 42.0,
          "resets_at": "2026-09-14T02:50:00+05:30",
          "window_minutes": 300
        },
        "weekly": {...}
      }
    }

The window keys are derived from the reported window length, not hard-coded.
If a provider ever starts reporting a 24h window it shows up as "daily"
automatically and the widget renders it without any code change.

IMPORTANT - what the providers actually report
----------------------------------------------
Neither Claude Code nor Codex reports a *daily* usage figure today.  Both
report a rolling session window and a weekly window.  Nothing here invents a
daily number; only what the tools actually return is shown.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

# The local timezone of this machine.  Claude prints its reset times already
# converted to local time, so this is what we attach to them.
LOCAL_TZ = datetime.now().astimezone().tzinfo


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def now_local() -> datetime:
    return datetime.now(tz=LOCAL_TZ)


def window_key_and_label(window_minutes):
    """Classify a limit window by its length.

    Returns (key, label) - e.g. (300 -> "session", "Session (5h)"),
    (1440 -> "daily", "Daily"), (10080 -> "weekly", "Weekly").
    """
    if window_minutes is None:
        return "session", "Session"
    m = int(window_minutes)
    if 1380 <= m <= 1500:                 # ~24h
        return "daily", "Daily"
    if m >= 6 * 1440:                     # ~a week or longer
        return "weekly", "Weekly"
    if m < 1380:                          # anything shorter than a day
        hours = m / 60.0
        if hours >= 1 and float(hours).is_integer():
            return "session", "Session ({}h)".format(int(hours))
        return "session", "Session ({}m)".format(m)
    return "window", "{} min".format(m)


def make_window(window_minutes, used_percent, resets_at, label=None):
    """Build one normalised window entry."""
    key, auto_label = window_key_and_label(window_minutes)
    return key, {
        "label": label or auto_label,
        "used_percent": None if used_percent is None else float(used_percent),
        "resets_at": resets_at.isoformat() if resets_at else None,
        "window_minutes": window_minutes,
    }


def _failed(name, error):
    return {
        "name": name,
        "ok": False,
        "error": error,
        "plan": None,
        "observed_at": None,
        "windows": {},
    }


# ==========================================================================
# Claude Code
# ==========================================================================
# Example of what `claude -p "/usage" --output-format text` prints:
#
#   You are currently using your subscription to power your Claude Code usage
#
#   Current session: 42% used - resets Sep 14, 2:50am (Asia/Colombo)
#   Current week (all models): 80% used - resets Sep 14, 12:30pm (Asia/Colombo)
#
# (the separator before "resets" is a middot)

CLAUDE_LINE_RE = re.compile(
    r"^\s*(?P<label>[^:]+?)\s*:\s*(?P<pct>\d+(?:\.\d+)?)\s*%\s*used"
    r"[^A-Za-z]*resets\s+(?P<reset>.+?)\s*$",
    re.IGNORECASE,
)

# "Sep 14, 2:50am (Asia/Colombo)" / "2:50am" / "Sep 14, 12:30pm"
CLAUDE_RESET_RE = re.compile(
    r"^(?:(?P<mon>[A-Za-z]{3,})\s+(?P<day>\d{1,2})\s*,\s*)?"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<ampm>am|pm)?"
    r"(?:\s*\((?P<tz>[^)]+)\))?\s*$",
    re.IGNORECASE,
)

MONTHS = {m.lower(): i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}


def parse_claude_reset(text, reference=None):
    """Turn Claude's human reset string into an aware datetime, or None."""
    match = CLAUDE_RESET_RE.match(text.strip())
    if not match:
        return None

    ref = reference or now_local()
    hour = int(match.group("hour"))
    minute = int(match.group("minute"))
    ampm = (match.group("ampm") or "").lower()
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0

    tzinfo = ref.tzinfo
    tz_name = match.group("tz")
    if tz_name:
        # Use the named zone when the tz database is available (the tzdata
        # package on Windows).  Otherwise fall back to local time, which is
        # what Claude already formatted the value in.
        try:
            from zoneinfo import ZoneInfo
            tzinfo = ZoneInfo(tz_name)
        except Exception:
            tzinfo = ref.tzinfo

    mon, day = match.group("mon"), match.group("day")
    if mon and day:
        month = MONTHS.get(mon[:3].lower())
        if not month:
            return None
        candidate = datetime(ref.year, month, int(day), hour, minute,
                             tzinfo=tzinfo)
        # The string carries no year - pick the one that lands nearest now.
        if candidate < ref - timedelta(days=180):
            candidate = candidate.replace(year=ref.year + 1)
        elif candidate > ref + timedelta(days=180):
            candidate = candidate.replace(year=ref.year - 1)
    else:
        candidate = ref.replace(hour=hour, minute=minute, second=0,
                                microsecond=0)
        if candidate <= ref:              # time already passed today
            candidate += timedelta(days=1)

    return candidate.replace(second=0, microsecond=0)


def parse_claude_output(text, reference=None):
    """Parse the CLI text into normalised windows."""
    windows = {}
    plan = None

    if "subscription" in text.lower():
        plan = "subscription"
    elif "api" in text.lower() and "credit" in text.lower():
        plan = "api"

    for raw_line in text.splitlines():
        match = CLAUDE_LINE_RE.match(raw_line)
        if not match:
            continue

        label = match.group("label").strip()
        low = label.lower()
        reset_at = parse_claude_reset(match.group("reset"), reference)
        percent = float(match.group("pct"))

        if "session" in low:
            # Claude's text does not state the session window length, so we
            # do not claim one.
            key, entry = make_window(None, percent, reset_at, label="Session")
        elif "week" in low:
            # Keep any qualifier Claude adds, e.g. "Current week (Opus)".
            qualifier = re.search(r"\(([^)]+)\)", label)
            nice = "Weekly"
            if qualifier and "all models" not in qualifier.group(1).lower():
                nice = "Weekly ({})".format(qualifier.group(1))
            key, entry = make_window(7 * 24 * 60, percent, reset_at, label=nice)
        else:
            continue

        # "Current week (all models)" and "Current week (Opus)" would collide
        # on the same key - keep them apart.
        unique = key
        suffix = 2
        while unique in windows:
            unique = "{}_{}".format(key, suffix)
            suffix += 1
        windows[unique] = entry

    return plan, windows


class ClaudeProvider:
    """Reads usage from the Claude Code CLI (same command the existing
    Claude/claude-usage.bat script uses, just captured instead of printed)."""

    name = "claude"

    def __init__(self, command=None, timeout=180):
        self.command = command or "claude"
        self.timeout = timeout

    def fetch(self):
        exe = shutil.which(self.command)
        if not exe:
            return _failed(self.name,
                           "'{}' not found in PATH".format(self.command))

        try:
            proc = subprocess.run(
                [exe, "-p", "/usage", "--output-format", "text"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=self.timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            return _failed(self.name,
                           "timed out after {}s".format(self.timeout))
        except OSError as exc:
            return _failed(self.name, str(exc))

        text = (proc.stdout or "") + "\n" + (proc.stderr or "")
        plan, windows = parse_claude_output(text)
        if not windows:
            snippet = " ".join(text.split())[:160]
            return _failed(self.name,
                           "could not parse CLI output: {}".format(snippet))

        return {
            "name": self.name,
            "ok": True,
            "error": None,
            "plan": plan,
            # The CLI reports live numbers, so they are current as of now.
            "observed_at": now_local().isoformat(),
            "windows": windows,
        }


# ==========================================================================
# OpenAI Codex
# ==========================================================================
# The Codex CLI has no non-interactive usage command (the existing
# Codex/codex-usage.ps1 drives the interactive TUI with SendKeys, which cannot
# be used by a background poller - it would steal focus and keystrokes).
#
# Codex does however record the rate-limit payload the API returns into its
# session rollout files:
#
#   ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl
#
# ... as "token_count" events holding:
#
#   "rate_limits": {"primary":   {"used_percent": 8.0,  "window_minutes": 300,
#                                 "resets_at": 1789334332},
#                   "secondary": {"used_percent": 6.0,  "window_minutes": 10080,
#                                 "resets_at": 1789881085},
#                   "plan_type": "plus"}
#
# Reading those is passive and costs nothing.  The trade-off is freshness:
# the numbers only move when Codex is actually used, so "observed_at" carries
# the event time and the widget shows it when it gets old.

def _iter_recent_rollouts(sessions_dir, limit=12):
    """Newest rollout files first."""
    pattern = os.path.join(sessions_dir, "**", "rollout-*.jsonl")
    files = glob.glob(pattern, recursive=True)
    files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return files[:limit]


def _last_rate_limit_event(path, tail_bytes=1024 * 1024):
    """Return (timestamp, rate_limits) of the last rate-limit event in a file."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > tail_bytes:
                fh.seek(size - tail_bytes)
                fh.readline()          # drop the partial first line
            chunk = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return None

    for line in reversed(chunk.splitlines()):
        if '"rate_limits"' not in line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        limits = (event.get("payload") or {}).get("rate_limits")
        if not isinstance(limits, dict):
            continue
        if limits.get("primary") is None and limits.get("secondary") is None:
            continue
        return event.get("timestamp"), limits
    return None


def _parse_event_timestamp(value):
    """Rollout timestamps look like '2026-09-13T16:46:38.697Z' (UTC)."""
    if not value:
        return None
    try:
        text = value.replace("Z", "+00:00")
        return datetime.fromisoformat(text).astimezone(LOCAL_TZ)
    except ValueError:
        return None


def parse_codex_rate_limits(limits):
    """Turn a Codex rate_limits payload into normalised windows."""
    windows = {}
    for slot in ("primary", "secondary"):
        info = limits.get(slot)
        if not isinstance(info, dict):
            continue

        resets_at = None
        epoch = info.get("resets_at")
        if isinstance(epoch, (int, float)):
            resets_at = datetime.fromtimestamp(epoch, tz=timezone.utc) \
                                .astimezone(LOCAL_TZ)
        elif info.get("resets_in_seconds") is not None:
            # Older Codex builds report a countdown instead of a timestamp.
            try:
                resets_at = now_local() + timedelta(
                    seconds=float(info["resets_in_seconds"]))
            except (TypeError, ValueError):
                resets_at = None

        key, entry = make_window(info.get("window_minutes"),
                                 info.get("used_percent"), resets_at)
        if key in windows:
            key = "{}_{}".format(key, slot)
        windows[key] = entry
    return windows


class CodexProvider:
    """Reads Codex rate limits from its local session rollout files."""

    name = "codex"

    def __init__(self, codex_home=None):
        self.codex_home = codex_home or os.environ.get("CODEX_HOME") or \
            os.path.join(os.path.expanduser("~"), ".codex")

    def fetch(self):
        sessions_dir = os.path.join(self.codex_home, "sessions")
        if not os.path.isdir(sessions_dir):
            return _failed(self.name,
                           "no Codex sessions folder at {}".format(sessions_dir))

        newest = None  # (timestamp, limits)
        for path in _iter_recent_rollouts(sessions_dir):
            found = _last_rate_limit_event(path)
            if not found:
                continue
            stamp = _parse_event_timestamp(found[0])
            if newest is None or (stamp and newest[0] and stamp > newest[0]) \
                    or newest[0] is None:
                newest = (stamp, found[1])
            # Files are walked newest-first; the first hit is almost always
            # the right one, but keep going a little in case of clock skew.
            if newest and newest[0] and (now_local() - newest[0]) < timedelta(minutes=5):
                break

        if not newest:
            return _failed(self.name,
                           "no rate-limit data found in Codex session files")

        stamp, limits = newest
        windows = parse_codex_rate_limits(limits)
        if not windows:
            return _failed(self.name, "Codex reported no usage windows")

        return {
            "name": self.name,
            "ok": True,
            "error": None,
            "plan": limits.get("plan_type"),
            "observed_at": stamp.isoformat() if stamp else None,
            "windows": windows,
        }


# --------------------------------------------------------------------------
def build_providers(config):
    """Create the enabled providers from the config dict."""
    providers = []
    settings = config.get("providers", {})

    claude_cfg = settings.get("claude", {})
    if claude_cfg.get("enabled", True):
        providers.append(ClaudeProvider(
            command=claude_cfg.get("command", "claude"),
            timeout=claude_cfg.get("timeout_seconds", 180),
        ))

    codex_cfg = settings.get("codex", {})
    if codex_cfg.get("enabled", True):
        providers.append(CodexProvider(codex_home=codex_cfg.get("codex_home")))

    return providers
