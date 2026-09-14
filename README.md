# AI Usage Monitor + Desktop Widget

Tracks Claude Code and OpenAI Codex usage in the background and shows it in a
small always-on-top card on the Windows desktop.

```text
Claude CLI          Codex session files
     │                      │
     └──────────┬───────────┘
                ▼
        usage_service/monitor.py          every 10 minutes
                │
                ├──► data/usage.json      (cache, survives restarts)
                │
                └──► 127.0.0.1:45654      (push, newline-delimited JSON)
                            │
                            ▼
                     widget/widget.py      always-on-top card
```

---

## Read this first: what the providers actually report

**Neither Claude Code nor Codex exposes a *daily* usage figure.** Both report a
rolling **session** window and a **weekly** window:

| Provider | What it reports | Where it comes from |
| -------- | --------------- | ------------------- |
| Claude   | `Current session: 42% used · resets Sep 14, 2:50am`<br>`Current week (all models): 80% used · resets Sep 14, 12:30pm` | `claude -p "/usage" --output-format text` |
| Codex    | `primary` window (300 min) and `secondary` window (10080 min), each with `used_percent` + `resets_at` | `~/.codex/sessions/**/rollout-*.jsonl` |

So the card shows **Session** and **Weekly** rather than Daily and Weekly.
Nothing is invented: no derived "daily" percentage, and no value is ever reset
to zero unless the provider itself reports the lower number.

Window labels come from the reported window length, not from hard-coded names
(`usage_service/providers.py` → `window_key_and_label`). If either provider
ever starts reporting a 1440-minute window, it appears as **Daily**
automatically with no code change.

The two providers are read completely independently, so different reset times,
reset dates and window lengths are handled naturally — as they already are
today (Claude's weekly resets Sunday 12:30 PM, Codex's the following Saturday
10:41 AM).

## Freshness: the two sources behave differently

* **Claude** is queried live every cycle, so its numbers are current.
* **Codex** has no non-interactive usage command. (The existing
  `Codex\codex-usage.ps1` drives the interactive TUI and types `/status` with
  `SendKeys` — that cannot run on a timer, it would steal focus and keystrokes
  every 10 minutes.) Instead the monitor reads the rate-limit payload Codex
  records in its own session files. That is free and silent, but **the numbers
  only change when you actually use Codex.**

So the card shows how old each provider's data is (`2h ago`) once it passes
`stale_after_minutes`. That label is the honest signal that Codex has not run
recently — not a fault.

---

## Running it

Two files, one click each:

| Double-click | What it does |
| ------------ | ------------ |
| **`START.bat`** | Starts the background monitor *and* the widget. Safe to click twice — anything already running is left alone. |
| **`STOP.bat`** | Closes both. |

Both run windowless. The monitor writes what it is doing to
`data\monitor.log`:

```text
[monitor] listening on 127.0.0.1:45654
[monitor] refreshing every 10.0 minutes
[monitor] 00:15:54 checking providers...
[monitor]   claude   ok
[monitor]   codex    ok
[monitor]   pushed to 1 widget(s)
```

The card appears in the top-right corner. Drag it anywhere, right-click for
**Refresh / Move to Top Right / Exit**, or close it with the **✕**.

For a widget that starts with Windows, put a shortcut to `START.bat` in your
Startup folder (`Win+R` → `shell:startup`).

The two parts are independent — either can be started, stopped or restarted
without the other, and the widget reconnects on its own within a few seconds.
To run or stop just one of them:

```bash
powershell -ExecutionPolicy Bypass -File scripts\appctl.ps1 status
```

To collect once in a console, without starting the server (useful for checking
parsing):

```bash
py -m usage_service.monitor --once
```

---

## The card

```text
● AI USAGE                    ✕
CLAUDE              subscription
Session                     52%
████████░░░░░░░░░░░░░░░░░░░░░░░
Resets Today 2:50 AM    2h 32m
Weekly                      80%
████████████████████████░░░░░░░
Resets Today 12:30 PM  12h 12m

CODEX                    2h ago
Session (5h)                 8%
██░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
Resets Today 2:48 AM    2h 31m
Weekly                       6%
█░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░
Resets Sun 10:41 AM     6d 10h

Updated 12:16 AM  ·  live
```

**Status dot**

| Colour | Meaning |
| ------ | ------- |
| 🟢 Green | Monitor connected and the data is current |
| 🟡 Yellow | Showing cached data — monitor stopped, or the data is older than two refresh cycles |
| 🔴 Red | No monitor and no cached data yet ("Waiting for data…") |

**Bar colour** is per window: green below 70%, amber 70–89%, red at 90%+.

**Reset display** is `Today 2:50 AM` / `Tomorrow 3:00 AM` / `Sun 10:41 AM` /
`Sep 26, 12:25 AM`, with the remaining time (`2h 32m`, `6d 10h`) on the right.
Countdowns tick every 30 seconds without needing a new fetch.

If the monitor is not running, the widget still starts and immediately shows
the last values from `data/usage.json`. With no cache at all it shows `--`
for every field and "Waiting for data…".

---

## Layout

```text
AIUsage/
│
├── Claude/claude-usage.bat        original script - unchanged
├── Codex/codex-usage.bat/.ps1     original scripts - unchanged
│
├── usage_service/
│   ├── providers.py               Claude + Codex adapters, normalising
│   ├── server.py                  local push server (TCP, JSON lines)
│   └── monitor.py                 the 10-minute loop
│
├── widget/
│   └── widget.py                  the desktop card (UI only, no fetching)
│
├── data/usage.json                latest cached snapshot
├── data/monitor.log               monitor output (windowless runs)
├── config/config.json             settings
├── START.bat                      starts monitor + widget
├── STOP.bat                       closes both
├── scripts/appctl.ps1             start/stop/status helper
└── README.md
```

The original `Claude\` and `Codex\` scripts are untouched and still work for
looking at usage by hand. The monitor reuses the same Claude command they do,
just captured instead of printed.

The widget performs **no** usage checks of its own — it renders what the
monitor sends.

## Settings — `config/config.json`

Optional: the defaults are built in, so the app runs without this file. To
change anything, copy `config/config.example.json` to `config/config.json`.
Your own copy is gitignored, along with `data/` (which holds your usage
figures).

```json
{
  "refresh_minutes": 10,
  "server": { "host": "127.0.0.1", "port": 45654 },
  "providers": {
    "claude": { "enabled": true, "command": "claude", "timeout_seconds": 180 },
    "codex":  { "enabled": true }
  },
  "widget": {
    "x": null, "y": null,
    "opacity": 0.96,
    "stale_after_minutes": 30
  }
}
```

| Key | Meaning |
| --- | ------- |
| `refresh_minutes` | How often the monitor checks both providers. |
| `server.port` | Loopback port the monitor listens on. |
| `providers.*.enabled` | Turn a provider off entirely. |
| `providers.claude.command` | Name/path of the Claude CLI. |
| `providers.codex.codex_home` | Override if Codex does not live in `~/.codex`. |
| `widget.x` / `widget.y` | Last position — written automatically. `null` = top-right. |
| `widget.opacity` | `0.0`–`1.0`. |
| `widget.stale_after_minutes` | When a provider's data starts showing its age. |

Note: each Claude check runs the CLI, which counts as a small amount of Claude
usage itself. At 10 minutes that is ~144 checks a day. Raise
`refresh_minutes` if you would rather not spend that.

## Cached data — `data/usage.json`

```json
{
  "providers": {
    "claude": {
      "name": "claude",
      "ok": true,
      "error": null,
      "plan": "subscription",
      "observed_at": "2026-09-14T00:16:16+05:30",
      "windows": {
        "session": { "label": "Session",  "used_percent": 52.0,
                     "resets_at": "2026-09-14T02:50:00+05:30",
                     "window_minutes": null },
        "weekly":  { "label": "Weekly",   "used_percent": 80.0,
                     "resets_at": "2026-09-14T12:30:00+05:30",
                     "window_minutes": 10080 }
      }
    },
    "codex": { "...": "same shape" }
  },
  "last_updated": "2026-09-14T00:16:16+05:30"
}
```

Written atomically (temp file + rename), so the widget never reads half a file.

If a provider fails on a cycle, its previous values are kept and marked rather
than being blanked — a failed check must not look like a reset.

## How resets are handled

Reset times are always whatever the provider reported; the widget only formats
them. When a window rolls over, the provider reports the new percentage and the
new `resets_at` on the next check, and the card follows. Nothing is ever forced
to `0%` locally. In the worst case the card is up to `refresh_minutes` behind a
reset, and right-click → **Refresh** closes that gap immediately.

## Protocol

Newline-delimited JSON over loopback TCP.

* On connect the server sends the current snapshot immediately, so a restarted
  widget is populated at once.
* On every collection the snapshot is pushed to all connected widgets.
* The widget can send `{"command": "refresh"}` to make the monitor check now
  (this is what right-click → Refresh does).

Loopback-only, stdlib-only, nothing exposed to the network. A WebSocket would
need a handshake implementation for no practical gain at this scale.

## Adding another provider

1. Add a class in `usage_service/providers.py` with a `name` and a `fetch()`
   returning the shape above (`make_window()` does the normalising).
2. Register it in `build_providers()`.

The widget renders any provider and any number of windows it finds in the
snapshot — no UI changes needed.
