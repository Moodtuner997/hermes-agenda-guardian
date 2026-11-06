"""A stand-in for the Google Workspace skill's script: an in-memory calendar behind the same argv and JSON.
It records every call, so a test can prove which events were (or were not) touched."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from agenda_guardian.sources import GOOGLE_SCRIPT


def install_script(home) -> None:
    script = home / GOOGLE_SCRIPT
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("# stand-in\n", encoding="utf-8")


class FakeGoogle:
    def __init__(self):
        self.events: list[dict] = []
        self.calls: list[list[str]] = []
        self._counter = 0

    def add(self, summary: str, start: datetime, end: datetime, description: str = "", event_id: str = "") -> str:
        self._counter += 1
        event_id = event_id or f"seed-{self._counter}"
        self.events.append({"id": event_id, "summary": summary, "start": start.isoformat(), "end": end.isoformat(),
                            "description": description, "status": "confirmed", "htmlLink": f"https://cal/{event_id}"})
        return event_id

    def weekly(self, summary: str, weekday: int, start: str, end: str, first, weeks: int, skip=()) -> None:
        """The same event on one weekday of ``weeks`` consecutive weeks from the Monday ``first``."""
        for w in range(weeks):
            if w in skip:
                continue
            day = first + timedelta(weeks=w, days=weekday - 1)
            self.add(summary, datetime.fromisoformat(f"{day}T{start}:00"), datetime.fromisoformat(f"{day}T{end}:00"))

    def ids(self) -> set[str]:
        return {e["id"] for e in self.events}

    def __call__(self, argv, **_):
        self.calls.append(list(argv))
        action = argv[3]
        if action == "list":
            return SimpleNamespace(returncode=0, stdout=json.dumps(self.events), stderr="")
        if action == "create":
            opt = dict(zip(argv[4::2], argv[5::2]))
            self._counter += 1
            event_id = f"made-{self._counter}"
            self.events.append({"id": event_id, "summary": opt["--summary"], "start": opt["--start"],
                                "end": opt["--end"], "description": opt.get("--description", ""),
                                "status": "confirmed", "htmlLink": f"https://cal/{event_id}"})
            return SimpleNamespace(returncode=0, stdout=json.dumps(
                {"status": "created", "id": event_id, "summary": opt["--summary"],
                 "htmlLink": f"https://cal/{event_id}"}), stderr="")
        if action == "delete":
            self.events = [e for e in self.events if e["id"] != argv[4]]
            return SimpleNamespace(returncode=0, stdout=json.dumps({"status": "deleted", "eventId": argv[4]}),
                                   stderr="")
        return SimpleNamespace(returncode=2, stdout="", stderr="unknown action")

    def deleted(self) -> list[str]:
        return [c[4] for c in self.calls if c[3] == "delete"]
