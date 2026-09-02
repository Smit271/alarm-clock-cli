# alarmclock

A command-line alarm clock. Set as many alarms as you like, give each one a
description, and choose whether it repeats. A watcher running in a terminal
rings each alarm at its time, reads the description aloud, and offers snooze or
dismiss. No dependencies beyond the Python standard library.

## Install

```bash
python3 -m pip install -e .
```

That puts an `alarm` command on your PATH.

## Quick start

```bash
alarm add 07:00 -d "Wake up" -r weekdays   # every Monday to Friday
alarm in 20m -d "Tea"                      # a one-off, 20 minutes from now
alarm list                                 # what is set, and when it next fires
alarm run                                  # leave this open; it rings the alarms
```

When an alarm fires you get a banner, a sound, the description spoken aloud, and
a prompt:

```
================================================
  ALARM  07:00
  Wake up
================================================
  [s] snooze 9m    [d] dismiss
```

## `alarm run` must be open

Alarms ring only while `alarm run` is going in a terminal. Nothing is
registered with launchd or cron, and there is no background daemon — if no
watcher is running, nothing rings.

You do not have to restart it to change anything. The watcher re-reads its
alarms every tick, so `alarm add` from any other terminal is picked up within
30 seconds. It also survives the laptop sleeping: an alarm whose time passed
more than 5 minutes ago is reported as missed rather than going off at the
wrong time.

## Commands

| Command | What it does |
|---|---|
| `alarm add <time>` | Add an alarm at a clock time |
| `alarm in <duration>` | Add a one-off alarm a duration from now |
| `alarm list [--all]` | List alarms with their next fire time and a countdown; `--all` includes disabled ones |
| `alarm rm <id>...` | Delete alarms |
| `alarm enable <id>...` | Turn alarms back on |
| `alarm disable <id>...` | Turn alarms off without deleting them |
| `alarm clean` | Delete one-off alarms that have already fired or been missed |
| `alarm run [--once]` | Watch for alarms and ring them; `--once` makes a single pass and exits |

`add` and `in` both accept:

| Option | Meaning |
|---|---|
| `-d`, `--description` | Text shown and spoken when the alarm rings |
| `--sound NAME` | Sound to play, e.g. `Glass` (default: `Submarine`) |
| `--snooze MIN` | Minutes added per snooze press (default: 9) |

`add` also takes `-r`/`--recurrence`.

## Formats

**Times:** `07:00`, `7:00`, `19:30`, `7am`, `7:30pm`

**Durations:** `45s`, `20m`, `2h`, `1h30m`

**Recurrence:** `once` (the default), `daily`, `weekdays`, `weekends`, or a
comma-separated list such as `mon,wed,fri`

A one-off alarm is pinned to a real date when you create it, so `alarm add
07:00` typed at 23:00 rings tomorrow morning — once — rather than becoming a
daily alarm.

## Sounds

On macOS, any name from `/System/Library/Sounds` works: `Glass`, `Ping`,
`Sosumi`, `Submarine`, `Hero`, and so on. Descriptions are spoken with `say` on
macOS and `spd-say` on Linux. If no player or speech binary is available, the
alarm falls back to the terminal bell.

## Where alarms are stored

`~/.config/alarmclock/alarms.json`, or `$XDG_CONFIG_HOME/alarmclock` if that is
set. Override the whole location with `ALARM_CLOCK_HOME`:

```bash
ALARM_CLOCK_HOME=/tmp/scratch alarm list
```

Writes are atomic and locked, so adding an alarm in one terminal cannot corrupt
or clobber what a running watcher writes in another.

## Development

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest
```

The test suite runs in about a second because the watcher takes its clock and
its ringer as injected dependencies — a nine-minute snooze is tested by moving
a fake clock, never by waiting.

The design and the implementation plan are in [docs/](docs/).
