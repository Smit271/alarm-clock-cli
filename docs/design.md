# alarmclock — Design Spec

Date: 2026-09-02
Status: approved, ready for implementation planning

## 1. Purpose

A command-line alarm clock. A user sets alarms at clock times, gives each one a
description, and chooses whether it repeats. A watcher process running in a
terminal rings the alarm at its time, speaks the description aloud, and offers
snooze or dismiss.

Success criteria:

- An alarm set for a future time rings at that time, within one second.
- Alarms added from one terminal are picked up by an already-running watcher
  without restarting it.
- Recurring alarms fire on the correct days indefinitely; one-off alarms fire
  exactly once.
- All scheduling behaviour is covered by tests that run in under a second, with
  no real waiting.

Non-goals: a background daemon, OS-level scheduling (launchd/cron), a GUI,
sync across machines, timezone-aware alarms.

## 2. Ring model

`alarm run` is a foreground watcher. The user leaves it open in a terminal; it
sleeps until the next alarm and rings. Any other terminal can add, remove or
modify alarms, and the running watcher observes those changes.

This was chosen over a detached daemon or launchd plists because it has no
pidfile, log-rotation or stale-process handling, works identically on macOS and
Linux, and can be driven end-to-end by tests. The trade-off is explicit: if no
watcher is running, nothing rings. Adding a daemon later is purely additive —
it would wrap the same loop.

## 3. Data model

A single `Alarm` dataclass, serialised to JSON.

| Field | Type | Meaning |
|---|---|---|
| `id` | `int` | Small, stable, user-facing. Referenced as `alarm rm 3`. |
| `time` | `str` | `HH:MM:SS`, 24-hour, local. Displayed as `HH:MM`. |
| `days` | `List[int]` | Weekdays it repeats on, Monday=0. Empty list means one-off. |
| `date` | `Optional[str]` | `YYYY-MM-DD`. Set if and only if `days` is empty. |
| `description` | `str` | Free text. Spoken aloud when the alarm rings. May be empty. |
| `enabled` | `bool` | Disabled alarms never fire and are hidden from the default listing. |
| `sound` | `Optional[str]` | Sound name overriding the default. |
| `snooze_minutes` | `int` | Minutes added per snooze press. Default 9. |
| `snoozed_until` | `Optional[str]` | ISO datetime. Overrides the normal schedule while set. |
| `last_fired` | `Optional[str]` | ISO datetime of the most recent occurrence already handled. |
| `outcome` | `Optional[str]` | `dismissed` or `missed`, set only on a finished one-off. |
| `created_at` | `str` | ISO datetime, for stable list ordering. |

Invariants:

- `days` empty XOR `date` set. Exactly one of the two shapes is valid.
- `id` is unique within the store and is never reused after deletion.
- `time` is stored to second precision so `alarm in 45s` is exact, but the CLI
  accepts and displays minute precision.
- `last_fired` records the scheduled time of the occurrence that was handled,
  not the wall-clock moment it was answered. This is what makes an occurrence
  handled-exactly-once, and it is the field that stops a dismissed alarm from
  ringing again on the next tick.
- `outcome` is only ever set on a one-off. A recurring alarm has no terminal
  state: a missed or dismissed occurrence simply advances `last_fired`.

Recurrence presets are stored as day-sets, not as a separate kind field:
`daily` = `[0,1,2,3,4,5,6]`, `weekdays` = `[0,1,2,3,4]`,
`weekends` = `[5,6]`, and explicit `mon,wed,fri` = `[0,2,4]`. There is one
scheduling concept, not two, and the listing re-derives the friendly preset
name for display.

One-off alarms carry a concrete date, resolved when the alarm is created. An
alarm added at 23:00 for `07:00` stores tomorrow's date, so it fires once
tomorrow morning rather than becoming an implicit daily alarm.

## 4. Scheduling

`schedule.next_occurrence(alarm, after) -> Optional[datetime]` is a pure
function with no I/O. It answers one narrow question — *what is the first time
this alarm is scheduled for, strictly after the given moment* — and it is the
core of the tool and the most heavily tested unit.

1. If `enabled` is false, return `None`.
2. One-off (`days` empty): return `datetime.combine(date, time)` if that is
   strictly after `after`, else `None`. A one-off has exactly one occurrence,
   so once it is behind `after` there is nothing left to return.
3. Recurring: scan the 8 calendar days starting with `after`'s date and return
   the first `datetime.combine(day, time)` that is strictly after `after` and
   whose weekday is in `days`. Eight days rather than seven so that the
   Sunday-to-Monday wraparound is covered when today's occurrence has already
   passed.

Callers supply `after` rather than the function reading the clock, which is
what lets the same function serve two different questions:

- **The watcher** passes `after = last_fired`, falling back to `created_at`
  when the alarm has never fired, so it sees the earliest occurrence *not yet
  handled* — including one already in the past, which is precisely how a due or
  missed alarm is detected.
- **The listing** passes `after = max(last_fired, now)`, so it shows the next
  genuinely upcoming time and never advertises a moment that has gone.

Snooze is deliberately not part of this function. `snoozed_until` is a
watcher-level override checked before the schedule, so that snoozing never
perturbs the underlying recurrence.

All datetimes are naive local time. An alarm clock's contract is that 7am stays
7am; converting to UTC would shift alarms by an hour across a DST boundary. The
consequences are accepted and documented: on the day a DST forward jump skips
the alarm's hour, the alarm does not fire that day; on a backward jump the
repeated hour cannot ring twice, because `last_fired` has already marked that
occurrence handled.

## 5. The run loop

`watcher.run(store, clock, ringer)` loops:

1. Reload the store from disk.
2. For each alarm, if `snoozed_until` is set, that is the target; otherwise the
   target is `next_occurrence(alarm, after=last_fired or created_at)` — the
   earliest occurrence not yet handled. `created_at` is the floor for an alarm
   that has never fired, because an occurrence from before the alarm existed
   was never missed and must not be reported as such.
3. A target is **due** if `target <= now < target + grace`, where grace is 5
   minutes. Ring the alarm with the earliest due target.
4. A target older than the grace window is **missed**. Either way — rung and
   answered, or missed — the occurrence is marked handled by setting
   `last_fired = target` and clearing `snoozed_until`. A recurring alarm then
   naturally advances to its next occurrence; a one-off additionally records
   `outcome` and sets `enabled = false`.
5. Sleep for `min(30s, seconds until the nearest target)`, then repeat.

Marking the occurrence handled via `last_fired` is what makes ringing
exactly-once. Without it, an alarm dismissed at 07:00:05 would still be inside
its grace window on the next tick and would ring again, and again, until the
window closed.

Sleeping in bounded ticks rather than one long sleep buys three properties: an
alarm added from another terminal is noticed within 30 seconds, a laptop
suspend or a wall-clock jump cannot cause the loop to overshoot an alarm, and
the shutdown path stays responsive to Ctrl-C.

The grace window is what makes suspend behave sensibly. If the machine sleeps
through an alarm and wakes 20 minutes later, the alarm is reported as missed
rather than ringing at a time the user did not ask for.

`alarm run --once` performs a single pass and exits, for scripting and tests.

## 6. Ringing

`ring.Ringer` is an interface with one method, `ring(alarm)`. The watcher
depends on the interface, so tests inject a `FakeRinger` that records calls.

The real implementation:

- Prints a banner with the time and description.
- Plays a sound on a loop until answered: `afplay` with a
  `/System/Library/Sounds/*.aiff` file on macOS, `paplay` then `aplay` on
  Linux, and the terminal bell as a last resort.
- Speaks the description once via `say` on macOS or `spd-say` on Linux. Skipped
  silently when the description is empty or no speech binary exists.
- Reads a single keypress: `s` snoozes, `d` dismisses. On a POSIX TTY this uses
  `termios` raw mode; when stdin is not a TTY it falls back to line-based
  `input()`.
- Stops on its own after 5 minutes unanswered, which the watcher treats exactly
  as a missed occurrence, so an unattended terminal does not ring indefinitely.

Every subprocess call is wrapped so that a missing binary degrades to the
terminal bell rather than raising.

Snooze sets `snoozed_until = now + snooze_minutes` and saves, leaving
`last_fired` untouched so the occurrence stays open until it is actually
answered. Dismiss marks the occurrence handled per section 5; for a one-off it
sets `outcome = "dismissed"` and `enabled = false`, so the alarm survives in
the listing as `done` and is removed by `alarm clean` rather than disappearing
silently.

## 7. Storage

Location, in precedence order: `$ALARM_CLOCK_HOME`, then
`$XDG_CONFIG_HOME/alarmclock`, then `~/.config/alarmclock`. The file is
`alarms.json`:

```json
{"version": 1, "next_id": 4, "alarms": [ ... ]}
```

Writes go to a temporary file in the same directory followed by `os.replace`,
so the store is never observed half-written. Every mutation is a
read-modify-write under an `fcntl.flock` on a sibling lock file, which prevents
the watcher's snooze write from clobbering a concurrent `add` from another
terminal.

Failure handling: a missing file yields an empty store. A corrupt file is moved
aside to `alarms.json.corrupt-<timestamp>` and an empty store is used, with a
message on stderr — the tool stays usable and the old data is recoverable.
`version` is present so a future schema change can migrate rather than guess.

## 8. Command-line interface

```
alarm add <time> [-d DESC] [-r RECURRENCE] [--sound NAME] [--snooze MIN]
alarm in <duration> [-d DESC]
alarm list [--all]
alarm rm <id>...
alarm enable <id>...
alarm disable <id>...
alarm run [--once]
alarm clean
```

- `<time>` accepts `07:00`, `7:00`, `19:30`, `7am`, `7:30pm`.
- `<duration>` accepts `45s`, `20m`, `2h`, `1h30m`.
- `-r` accepts `once` (the default), `daily`, `weekdays`, `weekends`, or a
  comma-separated day list such as `mon,wed,fri`.
- `alarm in` is sugar for a one-off alarm at now-plus-duration; it resolves to
  the same stored shape as `add`.
- `list` shows id, time, recurrence, description, and the next fire time with a
  human countdown. By default it hides disabled alarms; `--all` shows them,
  with the state derived from `outcome`: `done` for `dismissed`, `missed` for
  `missed`, and `off` when `outcome` is unset and the user disabled it by hand.
- `clean` deletes one-off alarms that have an `outcome`. Alarms disabled by
  hand are left alone, so `clean` can never throw away something the user
  intended to re-enable.

Every command exits 0 on success and 2 on user error, printing the reason to
stderr. Invalid times, unknown recurrence tokens and unknown ids are user
errors, never tracebacks.

## 9. Testing

pytest is the only development dependency. Two seams make the system testable
without waiting:

- `Clock`, with `now()` and `sleep(seconds)`. `FakeClock` advances its own
  notion of time instantly when slept on, so a nine-minute snooze is tested in
  microseconds.
- `Ringer`, whose fake records which alarms were rung and returns a scripted
  sequence of snooze/dismiss answers.

Coverage by module:

- `parsing` — every accepted time and duration form, plus rejection of
  `25:00`, `7pmm`, `20x`, empty input.
- `schedule` — one-off before and after `after`, disabled, each preset, the
  day-boundary case where today's time has passed, Sunday-to-Monday
  wraparound, and the exact-boundary case where `after` equals an occurrence
  (which must return the following one, never the same one).
- `store` — round trip, missing file, corrupt file quarantine, atomic write,
  id allocation without reuse.
- `watcher` — a recurring alarm rings exactly once at its occurrence and does
  not ring again on the following ticks inside the grace window; it then rings
  again at its next scheduled occurrence. Snooze re-fires after the interval
  and can be repeated. Dismiss ends it. Missed-beyond-grace is not rung but is
  marked handled, so it does not re-trigger. An alarm added mid-run is picked
  up on the next tick.
- `cli` — each command end to end against a temporary store directory,
  including the exit codes for user errors.

## 10. Packaging

`pyproject.toml` with a `[project.scripts]` entry point mapping `alarm` to
`alarmclock.cli:main`, so the tool is a real command after
`pip install -e .`. The runtime has no third-party dependencies — argparse,
json, datetime, subprocess, termios and fcntl are all stdlib.

The target is Python 3.9, matching the installed interpreter: no `X | Y`
annotations evaluated at runtime, no `match` statements, and
`typing.Optional`/`typing.List` rather than the builtin generics.
