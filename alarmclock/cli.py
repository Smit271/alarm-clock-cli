"""The argparse front end."""

import argparse
import sys
from datetime import datetime, timedelta
from typing import List, Optional

from . import parsing
from .clock import RealClock
from .models import OUTCOME_DISMISSED, OUTCOME_MISSED, Alarm, from_iso, to_iso
from .ring import ConsoleRinger
from .schedule import next_occurrence
from .store import Store, default_store_dir
from .watcher import Watcher


class UserError(Exception):
    """Something the user got wrong. Reported on stderr with exit code 2."""


def state_of(alarm: Alarm) -> str:
    if alarm.enabled:
        return "on"
    if alarm.outcome == OUTCOME_DISMISSED:
        return "done"
    if alarm.outcome == OUTCOME_MISSED:
        return "missed"
    return "off"


def _resolve_one_off_date(clock_time, now: datetime) -> str:
    """Pin a one-off to a real date: today if the time is still ahead, else tomorrow."""
    moment = datetime.combine(now.date(), clock_time)
    if moment <= now:
        moment += timedelta(days=1)
    return moment.date().isoformat()


def _append(store, **fields) -> Alarm:
    with store.transaction() as data:
        alarm = Alarm(id=data.next_id, created_at=to_iso(datetime.now()), **fields)
        data.alarms.append(alarm)
        data.next_id += 1
    return alarm


def _describe(alarm: Alarm) -> str:
    parts = ["alarm {}".format(alarm.id), alarm.time[:5], alarm.recurrence_label()]
    if alarm.description:
        parts.append("- {}".format(alarm.description))
    return " ".join(parts)


def cmd_add(args, store) -> int:
    clock_time = parsing.parse_time(args.time)
    days = parsing.parse_recurrence(args.recurrence)
    date = None if days else _resolve_one_off_date(clock_time, datetime.now())
    alarm = _append(store, time=clock_time.strftime("%H:%M:%S"), days=days, date=date,
                    description=args.description, sound=args.sound,
                    snooze_minutes=args.snooze)
    print("Added {}".format(_describe(alarm)))
    return 0


def cmd_in(args, store) -> int:
    moment = (datetime.now() + parsing.parse_duration(args.duration)).replace(microsecond=0)
    alarm = _append(store, time=moment.strftime("%H:%M:%S"), days=[],
                    date=moment.date().isoformat(), description=args.description,
                    sound=args.sound, snooze_minutes=args.snooze)
    print("Added {} ({})".format(
        _describe(alarm), parsing.format_countdown(moment - datetime.now())))
    return 0


def cmd_list(args, store) -> int:
    now = datetime.now()
    rows = []
    for alarm in sorted(store.read().alarms, key=lambda a: (a.time, a.id)):
        if not alarm.enabled and not args.all:
            continue
        after = now
        if alarm.last_fired:
            after = max(after, from_iso(alarm.last_fired))
        upcoming = next_occurrence(alarm, after)
        when = "-"
        if upcoming is not None:
            when = "{} ({})".format(upcoming.strftime("%a %H:%M"),
                                    parsing.format_countdown(upcoming - now))
        rows.append((str(alarm.id), alarm.time[:5], alarm.recurrence_label(),
                     state_of(alarm), when, alarm.description))

    if not rows:
        print("No alarms. Add one with: alarm add 07:00 -d \"Wake up\" -r weekdays")
        return 0

    headers = ("ID", "TIME", "REPEATS", "STATE", "NEXT", "DESCRIPTION")
    widths = [max(len(row[i]) for row in ((headers,) + tuple(rows)))
              for i in range(len(headers))]
    template = "  ".join("{:<" + str(width) + "}" for width in widths)
    print(template.format(*headers).rstrip())
    for row in rows:
        print(template.format(*row).rstrip())
    return 0


def _apply_to_ids(store, ids: List[int], action) -> None:
    with store.transaction() as data:
        known = {alarm.id: alarm for alarm in data.alarms}
        unknown = [str(i) for i in ids if i not in known]
        if unknown:
            raise UserError("no alarm with id {}".format(", ".join(unknown)))
        action(data, [known[i] for i in ids])


def cmd_rm(args, store) -> int:
    def action(data, targets):
        doomed = {alarm.id for alarm in targets}
        data.alarms[:] = [a for a in data.alarms if a.id not in doomed]

    _apply_to_ids(store, args.ids, action)
    print("Removed {} alarm(s)".format(len(args.ids)))
    return 0


def cmd_enable(args, store) -> int:
    def action(data, targets):
        for alarm in targets:
            alarm.enabled = True
            # A re-enabled alarm is live again, so its terminal state must go.
            alarm.outcome = None
            alarm.snoozed_until = None

    _apply_to_ids(store, args.ids, action)
    print("Enabled {} alarm(s)".format(len(args.ids)))
    return 0


def cmd_disable(args, store) -> int:
    def action(data, targets):
        for alarm in targets:
            alarm.enabled = False
            alarm.snoozed_until = None

    _apply_to_ids(store, args.ids, action)
    print("Disabled {} alarm(s)".format(len(args.ids)))
    return 0


def cmd_clean(args, store) -> int:
    removed = 0
    with store.transaction() as data:
        keep = [a for a in data.alarms if not (a.is_one_off and a.outcome)]
        removed = len(data.alarms) - len(keep)
        data.alarms[:] = keep
    print("Removed {} finished alarm(s)".format(removed))
    return 0


def cmd_run(args, store) -> int:
    watcher = Watcher(store, RealClock(), ConsoleRinger())
    if not args.once:
        print("Watching for alarms. Press Ctrl-C to stop.")
    try:
        watcher.run(once=args.once)
    except KeyboardInterrupt:
        print("\nStopped watching.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alarm", description="A command-line alarm clock.")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True  # Python 3.9 argparse needs this set explicitly.

    def add_alarm_options(sub):
        sub.add_argument("-d", "--description", default="",
                         help="text shown and spoken when the alarm rings")
        sub.add_argument("--sound", default=None,
                         help="sound name, e.g. Glass (default: Submarine)")
        sub.add_argument("--snooze", type=int, default=9,
                         help="minutes added per snooze (default: 9)")

    add_parser = subparsers.add_parser("add", help="add an alarm at a clock time")
    add_parser.add_argument("time", help="07:00, 19:30, 7am or 7:30pm")
    add_parser.add_argument("-r", "--recurrence", default="once",
                            help="once, daily, weekdays, weekends or mon,wed,fri")
    add_alarm_options(add_parser)
    add_parser.set_defaults(func=cmd_add)

    in_parser = subparsers.add_parser("in", help="add a one-off alarm a duration from now")
    in_parser.add_argument("duration", help="45s, 20m, 2h or 1h30m")
    add_alarm_options(in_parser)
    in_parser.set_defaults(func=cmd_in)

    list_parser = subparsers.add_parser("list", help="list alarms and when they next fire")
    list_parser.add_argument("--all", action="store_true", help="include disabled alarms")
    list_parser.set_defaults(func=cmd_list)

    for name, handler, help_text in (
        ("rm", cmd_rm, "delete alarms"),
        ("enable", cmd_enable, "re-enable alarms"),
        ("disable", cmd_disable, "turn alarms off without deleting them"),
    ):
        sub = subparsers.add_parser(name, help=help_text)
        sub.add_argument("ids", nargs="+", type=int, metavar="ID")
        sub.set_defaults(func=handler)

    clean_parser = subparsers.add_parser("clean", help="delete one-off alarms that have finished")
    clean_parser.set_defaults(func=cmd_clean)

    run_parser = subparsers.add_parser("run", help="watch for alarms and ring them")
    run_parser.add_argument("--once", action="store_true",
                            help="make a single pass and exit")
    run_parser.set_defaults(func=cmd_run)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    store = Store(default_store_dir())
    try:
        return args.func(args, store)
    except (parsing.ParseError, UserError) as error:
        print("error: {}".format(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
