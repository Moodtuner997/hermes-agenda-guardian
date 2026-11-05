"""Seeds an invented day for the demo video and the screenshots: rules, a small calendar, a few finished
tasks (so the calibration has something to say) and a handful of open ones. Nothing here is real data.

    python tests/make_demo_profile.py --home <HERMES_HOME> [--day 2026-11-09]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import date, datetime, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_plugin():
    spec = importlib.util.spec_from_file_location("agenda_guardian", ROOT / "__init__.py",
                                                  submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["agenda_guardian"] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", required=True, help="HERMES_HOME of the profile to seed")
    parser.add_argument("--day", default=date.today().isoformat())
    args = parser.parse_args()
    load_plugin()
    from agenda_guardian import commands
    from agenda_guardian.core import Guardian

    home, day = Path(args.home), date.fromisoformat(args.day)
    data = home / "plugin-data" / "agenda-guardian"
    data.mkdir(parents=True, exist_ok=True)
    calendar = data / "demo-calendar.json"
    calendar.write_text(json.dumps([
        {"summary": "Team sync", "start": f"{day}T10:00:00", "end": f"{day}T10:30:00"},
        {"summary": "Client call", "start": f"{day}T14:00:00", "end": f"{day}T15:00:00"},
        {"summary": "1:1 with Sam", "start": f"{day}T16:00:00", "end": f"{day}T16:30:00"},
    ]), encoding="utf-8")

    guardian = Guardian(data / "guardian.db", home, now=lambda: datetime.combine(day, time(8, 0)))
    for line in ("work_hours=09:00-17:30", "focus=09:00-11:30", "protected=lunch@12:30-13:30,walk@15:30-16:00",
                 f"calendar=file:{calendar}", "category=writing:60", "category=admin:15"):
        print(commands.run(guardian, f"set {line}"))
    # Past, finished work: the estimates were 30 and 15 minutes; it really took longer.
    for name, minutes, category, real in [("Write blog post", 30, "writing", 55), ("Write newsletter", 30, "writing", 60),
                                          ("Write release notes", 30, "writing", 45), ("Write FAQ", 30, "writing", 50),
                                          ("File receipts", 15, "admin", 20), ("Book travel", 15, "admin", 25),
                                          ("Pay invoices", 15, "admin", 15)]:
        commands.run(guardian, f'add "{name}" {minutes}m cat={category}')
        commands.run(guardian, f'done "{name}" {real}')
    for text in ('add "Draft the proposal" 60m cat=writing p=1 due=tomorrow',
                 'add "Expense report" 20m cat=admin p=2',
                 'add "Plan next sprint" 45m cat=planning p=2',
                 'add "Reply to Sam" 10m cat=admin p=3',
                 'add "Renew insurance" 15m cat=admin p=3 due=+4'):
        print(commands.run(guardian, text))


if __name__ == "__main__":
    main()
