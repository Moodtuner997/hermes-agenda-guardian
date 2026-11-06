"""The proactive side: activity sheets, the user's habits, proposals with reasons, writing to the calendar after a
yes, undoing it, and the "how long did it really take" question. Mixed into ``Guardian``; every public method
returns a dict with a ``text`` (what a person reads) and the same facts as data (what an agent reads)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from . import history, kinds as kindmod, planner, profile as prof, proposer, sources, store, writer
from .model import UserError
from .texts import day_name, join_and, tr

PROPOSAL_LIFETIME = timedelta(hours=24)
HISTORY_WEEKS = history.WEEKS
ASK_WINDOW = timedelta(hours=8)
WEEK, STAGED = "plan:week", "plan:stage"  # the "kind" of a proposal that holds several activities / given blocks (the colon keeps them apart from activity names)


class AgendaMixin:
    # --- switches -----------------------------------------------------------------------------------------
    def write_enabled(self) -> bool:
        return store.get_flag(self.conn, "calendar_write")

    def set_write(self, on: bool) -> dict:
        lang = self.lang()
        if on and self.profile()["calendar"]["type"] != "google":
            raise UserError(tr(lang, "write_needs_google"))
        store.set_flag(self.conn, "calendar_write", on)
        return {"ok": True, "calendar_write": on, "text": tr(lang, "write_on" if on else "write_off")}

    # --- activity sheets ----------------------------------------------------------------------------------
    def kind_set(self, name: str, real_min: int, before_min: int = 0, after_min: int = 0, window: str = "",
                 days: str = "") -> dict:
        lang = self.lang()
        existing = store.get_kind(self.conn, name)
        if not window:
            if not existing:
                raise UserError(tr(lang, "kind_window_needed"))
            window = "-".join(existing.win)
        kind = kindmod.build(name, real_min, before_min, after_min, window, days, lang)
        store.save_kind(self.conn, kind, self.now())
        return {"ok": True, "kind": self._kind_dict(kind), "text": tr(lang, "kind_saved", line=self._kind_line(kind))}

    def kind_remove(self, name: str) -> dict:
        lang = self.lang()
        if not store.remove_kind(self.conn, name):
            raise UserError(tr(lang, "kind_unknown", name=name, known=self._kind_names()))
        return {"ok": True, "text": tr(lang, "kind_removed", name=name)}

    def _kind_names(self) -> str:
        return ", ".join(k.name for k in store.kinds(self.conn)) or tr(self.lang(), "none")

    def _kind_line(self, kind) -> str:
        lang = self.lang()
        factor, count = store.factors(self.conn).get(kindmod.category(kind.name), (1.0, 0))
        days = ", ".join(day_name(lang, d) for d in kind.days) or tr(lang, "any_day")
        line = tr(lang, "kind_line", name=kind.name, real=kind.real_min, before=kind.before_min, after=kind.after_min,
                  start=kind.win[0], end=kind.win[1], days=days)
        if count >= store.MIN_SAMPLES and factor != 1.0:
            line += " " + tr(lang, "kind_measured", factor=factor, n=count)
        elif count:
            line += " " + tr(lang, "kind_measuring", n=count, need=store.MIN_SAMPLES)
        return line

    def _kind_dict(self, kind) -> dict:
        factor, count = store.factors(self.conn).get(kindmod.category(kind.name), (1.0, 0))
        return {"name": kind.name, "real_minutes": kind.real_min, "before_minutes": kind.before_min,
                "after_minutes": kind.after_min, "window": "-".join(kind.win), "weekdays": list(kind.days),
                "measured_factor": factor, "measurements": count}

    def kinds_view(self) -> dict:
        items = store.kinds(self.conn)
        lang = self.lang()
        text = "\n".join(self._kind_line(k) for k in items) if items else tr(lang, "kinds_none")
        return {"ok": True, "kinds": [self._kind_dict(k) for k in items], "text": text}

    # --- habits the calendar does not show ----------------------------------------------------------------
    def habit_add(self, day: str, span: str, label: str) -> dict:
        lang = self.lang()
        label = label.strip()
        if not label:
            raise UserError(tr(lang, "habit_label"))
        try:
            weekday = prof._one_day(day.strip().lower()[:3], lang)
            start, end = prof._range(span, lang)
        except ValueError as exc:
            raise UserError(str(exc))
        habit_id = store.add_habit(self.conn, weekday, start, end, label, self.now())
        return {"ok": True, "id": habit_id, "text": tr(lang, "habit_saved", id=habit_id, day=day_name(lang, weekday),
                                                       start=start, end=end, label=label)}

    def habit_remove(self, habit_id: int) -> dict:
        lang = self.lang()
        if not store.remove_habit(self.conn, habit_id):
            raise UserError(tr(lang, "habit_unknown", id=habit_id))
        return {"ok": True, "text": tr(lang, "habit_removed", id=habit_id)}

    def habits_view(self) -> dict:
        lang = self.lang()
        rows = store.habits(self.conn)
        lines = [tr(lang, "habit_line", id=h["id"], day=day_name(lang, h["weekday"]), start=h["start"],
                    end=h["end"], label=h["label"]) for h in rows]
        return {"ok": True, "habits": rows, "text": "\n".join(lines) if lines else tr(lang, "habits_none")}

    # --- proposals ----------------------------------------------------------------------------------------
    def propose(self, kind_name: str, count: int = 1, first: date | None = None, last: date | None = None,
                days: str = "") -> dict:
        lang, profile, now = self.lang(), self.profile(), self.now()
        kind = store.get_kind(self.conn, kind_name)
        if kind is None:
            raise UserError(tr(lang, "kind_unknown", name=kind_name, known=self._kind_names()))
        if profile["calendar"]["type"] == "none":
            raise UserError(tr(lang, "propose_need_calendar"))
        if not 1 <= count <= 7:
            raise UserError(tr(lang, "propose_count"))
        first = first or now.date()
        last = last or first + timedelta(days=6)
        if last < first or (last - first).days > 31:
            raise UserError(tr(lang, "propose_range"))
        try:
            force = tuple(prof._weekdays(days, lang)) if days.strip() else ()
        except ValueError as exc:
            raise UserError(str(exc))
        events, past, warnings = self._read_calendar(profile, first, last, now, lang)
        stats = history.analyse(past, now.date(), kind.win)
        factor = store.factors(self.conn).get(kindmod.category(kind.name), (1.0, 0))
        result = proposer.propose(kind, factor, count, first, last, events, store.habits(self.conn), stats,
                                  profile, now, force)
        result.update(kind=kind.name, wanted=count, warnings=warnings, first=first.isoformat(), last=last.isoformat())
        proposal_id = store.add_proposal(self.conn, kind.name, json.dumps(result, ensure_ascii=False), now)
        result["proposal_id"] = proposal_id
        result["calendar_write"] = self.write_enabled()
        result["questions"] = self._questions(result, lang)
        result["text"] = self._render_proposal(result, lang)
        result["ok"] = True
        return result

    def _read_calendar(self, profile: dict, first: date, last: date, now: datetime, lang: str):
        """The range asked for and the weeks before it, read once: (events, history events, warnings)."""
        monday = now.date() - timedelta(days=now.date().weekday())
        try:
            events, warnings = sources.fetch_range(profile, first, last, self.home, run=self._run,
                                                   urlopen=self._urlopen)
            past, more = sources.fetch_range(profile, monday - timedelta(weeks=HISTORY_WEEKS),
                                             monday - timedelta(days=1), self.home, run=self._run,
                                             urlopen=self._urlopen)
        except sources.SourceError as exc:
            raise UserError(tr(lang, "propose_unreadable", why=exc))
        return events, past, warnings + more

    def _questions(self, result: dict, lang: str) -> list[str]:
        out = []
        if result["sessions"]:
            names = join_and(lang, [s["weekday"] for s in result["sessions"]])
            out.append(tr(lang, "q_unlisted", days=names))
        out.append(tr(lang, "q_validate", id=result["proposal_id"]))
        return out

    def _render_proposal(self, r: dict, lang: str) -> str:
        head = tr(lang, "prop_head", id=r["proposal_id"], kind=r["kind"], n=len(r["sessions"]), wanted=r["wanted"])
        lines = [head, ""]
        if r["sessions"]:
            brief = tr(lang, "prop_brief", chosen=join_and(lang, [s["weekday"] for s in r["sessions"]]))
            if r["rejected"]:
                brief += " " + tr(lang, "prop_brief_out", rejected=join_and(
                    lang, [f"{x['weekday']} ({x['short']})" for x in r["rejected"]]))
            lines += [brief, ""]
        else:
            lines.append(tr(lang, "prop_none"))
        for index, s in enumerate(r["sessions"], 1):
            b0, st, en, b1 = (datetime.fromisoformat(s[k]) for k in ("block_start", "start", "end", "block_end"))
            lines.append(tr(lang, "prop_session", i=index, day=s["weekday"], date=f"{b0:%d/%m}",
                            block=f"{b0:%H:%M}-{b1:%H:%M}", start=f"{st:%H:%M}", end=f"{en:%H:%M}",
                            kind=r["kind"]))
            lines += [f"     - {x}" for x in s["reasons"]]
            lines += [f"     ! {x}" for x in s["notes"]]
        if r["missing"]:
            lines += ["", tr(lang, "prop_missing", n=r["missing"])]
        if r["adjacent"]:
            lines.append(tr(lang, "prop_adjacent"))
        if r["rejected"]:
            lines += ["", tr(lang, "prop_rejected")] + [f"  - {x['reason']}" for x in r["rejected"]]
        for w in r.get("warnings", []):
            lines.append(f"! {w}")
        lines += ["", tr(lang, "prop_before")] + [f"  - {q}" for q in r["questions"]]
        lines.append(tr(lang, "prop_writes_on" if r["calendar_write"] else "prop_writes_off", id=r["proposal_id"]))
        return "\n".join(lines)

    # --- a whole week in one request, and plans the agent composed -------------------------------------------
    def _requested_kind(self, spec: dict, lang: str):
        """One requested activity: the saved sheet (if any) completed by the numbers the user gave just now."""
        name = " ".join(str(spec.get("name", "")).lower().split())
        saved = store.get_kind(self.conn, name)

        def first(*values):
            return next((v for v in values if v not in (None, "")), None)

        real = first(spec.get("minutes"), saved and saved.real_min)
        if real is None:
            raise UserError(tr(lang, "week_minutes", name=name))
        window = first(spec.get("window"), saved and "-".join(saved.win))
        if not window:
            raise UserError(tr(lang, "kind_window_needed"))
        try:
            minutes = int(real)
            before = int(first(spec.get("before_minutes"), saved and saved.before_min, 0))
            after = int(first(spec.get("after_minutes"), saved and saved.after_min, 0))
            per_day, count = int(spec.get("per_day") or 0), int(spec.get("sessions") or 1)
        except (TypeError, ValueError):
            raise UserError(tr(lang, "week_number", name=name))
        for key, value, low, high in (("per_day", per_day, 0, 4), ("sessions", count, 1, 7)):
            if not low <= value <= high:
                raise UserError(tr(lang, "week_range", name=name, key=key, low=low, high=high))
        days = str(first(spec.get("days"), saved and ",".join(map(str, saved.days))) or "")
        kind = kindmod.build(name, minutes, before, after, str(window), days, lang)
        try:  # the days said just now are a wish; a saved sheet's days are only a preference
            force = tuple(prof._weekdays(str(spec["days"]), lang)) if spec.get("days") else ()
        except ValueError as exc:
            raise UserError(str(exc))
        return kind, per_day, count, force, bool(spec.get("remember"))

    def week_plan(self, activities: list, first: date | None = None, last: date | None = None) -> dict:
        """Several activities placed in one go, each around the events and around the ones placed before it.
        Nothing needs to be saved first: the numbers come with the request (a saved sheet only fills the gaps)."""
        lang, profile, now = self.lang(), self.profile(), self.now()
        if profile["calendar"]["type"] == "none":
            raise UserError(tr(lang, "propose_need_calendar"))
        if not isinstance(activities, list) or not 1 <= len(activities) <= 6 \
                or not all(isinstance(a, dict) for a in activities):
            raise UserError(tr(lang, "week_count"))
        wanted = [self._requested_kind(spec, lang) for spec in activities]  # every request checked before any read
        first = first or now.date()
        last = last or first + timedelta(days=6)
        if last < first or (last - first).days > 31:
            raise UserError(tr(lang, "propose_range"))
        events, past, warnings = self._read_calendar(profile, first, last, now, lang)
        habit_rows = store.habits(self.conn)
        taken: list[tuple[datetime, datetime]] = []
        sessions, rejected, summary = [], [], []
        for kind, per_day, count, force, remember in wanted:
            factor = store.factors(self.conn).get(kindmod.category(kind.name), (1.0, 0))
            stats = history.analyse(past, now.date(), kind.win)
            place = proposer.fill_days if per_day else proposer.propose
            part = place(kind, factor, per_day or count, first, last, events, habit_rows, stats, profile, now,
                         force, tuple(taken))
            for s in part["sessions"]:
                s["kind"] = kind.name
                taken.append((datetime.fromisoformat(s["block_start"]), datetime.fromisoformat(s["block_end"])))
            sessions += part["sessions"]
            rejected += [{**r, "kind": kind.name} for r in part["rejected"]]
            summary.append({"activity": kind.name, "mode": "daily" if per_day else "count", "per_day": per_day,
                            "wanted": part["wanted"] if per_day else count, "placed": len(part["sessions"]),
                            "missing": part["missing"], "window": "-".join(kind.win), "minutes": part["minutes"],
                            "pause_minutes": profile["break_min"]})
            if remember:
                store.save_kind(self.conn, kind, now)
        sessions.sort(key=lambda s: s["block_start"])
        result = {"sessions": sessions, "rejected": rejected, "activities": summary, "warnings": warnings,
                  "first": first.isoformat(), "last": last.isoformat()}
        return self._finish_plan(result, WEEK, "week_head", False, lang, now)

    def stage(self, blocks: list) -> dict:
        """Blocks the agent composed from what the user said (a fixed appointment, an evening spent elsewhere):
        checked against the calendar, then written, and taken back, like any proposal: the one way in."""
        from .core import parse_day

        lang, profile, now = self.lang(), self.profile(), self.now()
        if profile["calendar"]["type"] == "none":
            raise UserError(tr(lang, "propose_need_calendar"))
        if not isinstance(blocks, list) or not 1 <= len(blocks) <= 40 or not all(isinstance(b, dict) for b in blocks):
            raise UserError(tr(lang, "stage_count"))
        today, limit = now.date(), now.date() + timedelta(days=31)
        sessions = []
        for b in blocks:
            title = " ".join(str(b.get("title", "")).split())
            if not 1 <= len(title) <= 60:
                raise UserError(tr(lang, "stage_title"))
            day = parse_day(str(b.get("day", "")), today, lang)
            if not today <= day <= limit:
                raise UserError(tr(lang, "stage_range", last=limit.isoformat()))
            try:
                start, end = prof._range(f"{b.get('start', '')}-{b.get('end', '')}", lang)
            except ValueError as exc:
                raise UserError(str(exc))
            s0, s1 = planner.at(day, start), planner.at(day, end)
            why = " ".join(str(b.get("why") or "").split()) or tr(lang, "stage_said")
            sessions.append({"day": day.isoformat(), "weekday": day_name(lang, day.isoweekday()),
                             "block_start": s0.isoformat(), "start": s0.isoformat(), "end": s1.isoformat(),
                             "block_end": s1.isoformat(), "reasons": [why], "notes": [], "kind": title})
        sessions.sort(key=lambda s: s["start"])
        latest = None
        for s in sessions:
            if latest and s["start"] < latest["end"]:
                raise UserError(tr(lang, "stage_overlap", a=latest["kind"], b=s["kind"], day=latest["weekday"]))
            if latest is None or s["end"] > latest["end"]:
                latest = s
        first, last = date.fromisoformat(sessions[0]["day"]), date.fromisoformat(max(s["day"] for s in sessions))
        try:
            events, warnings = sources.fetch_range(profile, first, last, self.home, run=self._run,
                                                   urlopen=self._urlopen)
        except sources.SourceError as exc:
            raise UserError(tr(lang, "propose_unreadable", why=exc))
        clashes = []
        for s in sessions:
            s0, s1 = datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["end"])
            other = next((e for e in events if not e.all_day and e.start < s1 and e.end > s0), None)
            if other:
                clashes.append(tr(lang, "stage_clash", title=s["kind"], day=s["weekday"], start=f"{s0:%H:%M}",
                                  end=f"{s1:%H:%M}", other=other.title))
        if clashes:
            raise UserError("\n".join(clashes))
        result = {"sessions": sessions, "rejected": [], "warnings": warnings, "first": first.isoformat(),
                  "last": last.isoformat()}
        return self._finish_plan(result, STAGED, "stage_head", True, lang, now)

    def _finish_plan(self, result: dict, kind: str, head: str, show_reasons: bool, lang: str, now: datetime) -> dict:
        proposal_id = store.add_proposal(self.conn, kind, json.dumps(result, ensure_ascii=False), now)
        result.update(proposal_id=proposal_id, calendar_write=self.write_enabled())
        days = list(dict.fromkeys(s["weekday"] for s in result["sessions"]))
        result["questions"] = ([tr(lang, "q_unlisted", days=join_and(lang, days))] if kind == WEEK and days else []) \
            + [tr(lang, "q_validate", id=proposal_id)]
        result["text"] = self._render_plan(result, lang, tr(lang, head, id=proposal_id, n=len(result["sessions"])),
                                           show_reasons)
        result["ok"] = True
        return result

    @staticmethod
    def _render_plan(r: dict, lang: str, head: str, show_reasons: bool) -> str:
        def cap(text: str) -> str:
            return text[:1].upper() + text[1:]

        lines = [head, ""]
        by_day: dict[str, list[dict]] = {}
        for s in r["sessions"]:
            by_day.setdefault(s["day"], []).append(s)
        for day, items in by_day.items():
            lines.append(f"{items[0]['weekday']} {date.fromisoformat(day):%d/%m}")
            for s in items:
                start, end = datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["end"])
                lines.append(f"  {start:%H:%M}-{end:%H:%M} {cap(s['kind'])}")
                if show_reasons:
                    lines += [f"     - {x}" for x in s["reasons"]]
        if r.get("activities"):
            lines += ["", tr(lang, "week_why")]
            for a in r["activities"]:
                line = tr(lang, "week_each", name=cap(a["activity"]), got=a["placed"], wanted=a["wanted"])
                if a["mode"] == "daily":
                    start, end = a["window"].split("-")
                    line += tr(lang, "week_daily", per=a["per_day"], real=a["minutes"]["activity"], start=start,
                               end=end, pause=a["pause_minutes"])
                lines.append(line)
                if a["mode"] == "count":
                    for s in (x for x in r["sessions"] if x["kind"] == a["activity"]):
                        lines.append(f"  {s['weekday']} {date.fromisoformat(s['day']):%d/%m}")
                        lines += [f"     - {x}" for x in s["reasons"]]
                        lines += [f"     ! {x}" for x in s["notes"]]
            missing = sum(a["missing"] for a in r["activities"])
            if missing:
                lines += ["", tr(lang, "prop_missing", n=missing)]
        if r["rejected"]:
            lines += ["", tr(lang, "prop_rejected")] + [
                f"  - [{cap(x['kind'])}] {x['reason']}" if r.get("activities") and x.get("kind") else f"  - {x['reason']}"
                for x in r["rejected"][:8]]
        lines += [f"! {w}" for w in r.get("warnings", [])]
        lines += ["", tr(lang, "prop_before")] + [f"  - {q}" for q in r["questions"]]
        lines.append(tr(lang, "prop_writes_on" if r["calendar_write"] else "prop_writes_off", id=r["proposal_id"]))
        return "\n".join(lines)

    # --- writing, only after a yes --------------------------------------------------------------------------
    def confirm(self, proposal_id: int, days: str = "") -> dict:
        lang, profile, now = self.lang(), self.profile(), self.now()
        if not self.write_enabled():
            raise UserError(tr(lang, "confirm_off"))
        if profile["calendar"]["type"] != "google":
            raise UserError(tr(lang, "write_needs_google"))
        proposal = store.get_proposal(self.conn, proposal_id)
        if proposal is None:
            raise UserError(tr(lang, "confirm_unknown", id=proposal_id))
        if proposal["status"] != "pending":
            raise UserError(tr(lang, "confirm_done", id=proposal_id, status=tr(lang, "status_" + proposal["status"])))
        if now - datetime.fromisoformat(proposal["created_at"]) > PROPOSAL_LIFETIME:
            store.set_proposal_status(self.conn, proposal_id, "expired")
            raise UserError(tr(lang, "confirm_expired", id=proposal_id, kind=proposal["kind"]))
        kind = store.get_kind(self.conn, proposal["kind"])
        sessions = proposal["payload"]["sessions"]
        if days.strip():
            try:
                wanted = set(prof._weekdays(days, lang))
            except ValueError as exc:
                raise UserError(str(exc))
            sessions = [s for s in sessions if date.fromisoformat(s["day"]).isoweekday() in wanted]
        if not sessions:
            raise UserError(tr(lang, "confirm_nothing"))
        written, skipped, lines = [], [], []
        days_of = [date.fromisoformat(s["day"]) for s in sessions]
        try:  # the slots are read again, once for the whole range: a week is not twenty calendar calls
            current, _ = sources.fetch_range(profile, min(days_of), max(days_of), self.home, run=self._run,
                                             urlopen=self._urlopen)
        except sources.SourceError as exc:
            raise UserError(tr(lang, "propose_unreadable", why=exc))
        for s in sessions:
            b0, b1 = datetime.fromisoformat(s["block_start"]), datetime.fromisoformat(s["block_end"])
            clash = [e for e in current if not e.all_day and e.start < b1 and e.end > b0]
            if clash:
                skipped.append({"day": s["day"], "why": tr(lang, "confirm_clash", day=s["weekday"],
                                                           title=clash[0].title)})
                continue
            group = store.new_group(self.conn)
            name = s.get("kind") or proposal["kind"]  # a week or a staged plan holds several activities
            parts = self._parts(s, kind, name, lang)
            made = []
            for part, summary, start, end in parts:
                try:
                    event_id, link = writer.create(
                        self.home, profile.get("timezone", ""), "primary", summary, start, end,
                        f"{writer.marker(group, part)} {tr(lang, 'event_desc', id=group)}", self._run)
                except sources.SourceError as exc:
                    skipped.append({"day": s["day"], "why": tr(lang, "confirm_failed", day=s["weekday"], why=exc,
                                                               group=group)})
                    break
                store.record_written(self.conn, {
                    "event_id": event_id, "calendar_id": "primary", "group_id": group, "proposal_id": proposal_id,
                    "kind": name, "part": part, "summary": summary, "start": start.isoformat(),
                    "end": end.isoformat(), "link": link}, now)
                made.append({"part": part, "summary": summary, "link": link})
            if made:
                if proposal["kind"] == STAGED:  # a fixed block the user described: no "how long did it take"
                    store.mark_notified(self.conn, f"logged:{group}", now)
                written.append({"group": group, "day": s["day"], "events": made})
                lines.append(tr(lang, "confirm_line", group=group, kind=name, day=s["weekday"], date=f"{b0:%d/%m}",
                                block=f"{b0:%H:%M}-{b1:%H:%M}", n=len(made), link=made[0]["link"]))
        store.set_proposal_status(self.conn, proposal_id, "written" if written and not skipped else
                                  ("partial" if written else "failed"))
        lines += [f"! {x['why']}" for x in skipped]
        if written:
            lines.append(tr(lang, "confirm_undo"))
        return {"ok": bool(written), "written": written, "skipped": skipped, "text": "\n".join(lines)}

    @staticmethod
    def _parts(session: dict, kind, name: str, lang: str):
        label = name[:1].upper() + name[1:]
        b0, st, en, b1 = (datetime.fromisoformat(session[k]) for k in ("block_start", "start", "end", "block_end"))
        parts = []
        if st > b0:
            parts.append(("before", tr(lang, "part_before", name=label), b0, st))
        parts.append(("main", label, st, en))
        if b1 > en:
            parts.append(("after", tr(lang, "part_after", name=label), en, b1))
        return parts

    def undo(self, which: str = "last") -> dict:
        lang, profile, now = self.lang(), self.profile(), self.now()
        which = (which or "last").strip().lower()
        if which == "all":
            groups = sorted({r["group_id"] for r in store.written(self.conn)})
        elif which in ("last", ""):
            last = store.last_group(self.conn)
            groups = [last] if last else []
        elif which.lstrip("#").isdigit():
            groups = [int(which.lstrip("#"))]
        else:
            raise UserError(tr(lang, "undo_usage"))
        rows = [r for g in groups for r in store.written(self.conn, g)]
        if not rows:
            return {"ok": True, "removed": [], "text": tr(lang, "undo_none")}
        results, lines = [], []
        for row in rows:
            try:
                outcome = writer.remove(self.conn, self.home, profile.get("timezone", ""), row["event_id"], now,
                                        self._run)
            except sources.SourceError as exc:
                lines.append(tr(lang, "undo_failed", summary=row["summary"], why=exc))
                results.append({"event": row["summary"], "outcome": "failed"})
                continue
            results.append({"event": row["summary"], "outcome": outcome})
            lines.append(tr(lang, "undo_" + outcome, summary=row["summary"], start=row["start"][:16].replace("T", " ")))
        return {"ok": True, "removed": results, "text": "\n".join(lines)}

    # --- how long did it really take ------------------------------------------------------------------------
    def took(self, ref: str, minutes: int) -> dict:
        lang, now = self.lang(), self.now()
        ref = ref.strip().lstrip("#").lower()
        mains = [r for r in store.written(self.conn, live_only=False) if r["part"] == "main"]
        if ref.isdigit():
            row = next((r for r in mains if r["group_id"] == int(ref)), None)
        else:
            row = next((r for r in reversed(mains) if r["kind"] == ref and datetime.fromisoformat(r["end"]) <= now), None)
        if row is None:
            raise UserError(tr(lang, "took_unknown", ref=ref))
        if not 1 <= minutes <= 960:
            raise UserError(tr(lang, "done_range"))
        planned = int((datetime.fromisoformat(row["end"]) - datetime.fromisoformat(row["start"])).total_seconds() // 60)
        sheet = store.get_kind(self.conn, row["kind"])
        category = kindmod.category(row["kind"])
        # The ratio is measured against what the user SAID, not against the length that was written (already
        # corrected): otherwise a correct correction would pull its own factor back towards 1.
        store.log_sample(self.conn, category, sheet.real_min if sheet else planned, minutes, now)
        store.mark_notified(self.conn, f"logged:{row['group_id']}", now)
        factor, count = store.factors(self.conn).get(category, (1.0, 1))
        calib = (tr(lang, "took_start", n=count, need=store.MIN_SAMPLES) if count < store.MIN_SAMPLES
                 else tr(lang, "took_now", kind=row["kind"], factor=factor, n=count))
        return {"ok": True, "group": row["group_id"], "planned_minutes": planned, "real_minutes": minutes,
                "text": tr(lang, "took_msg", kind=row["kind"], planned=planned, real=minutes, calib=calib)}

    def kind_questions(self, now: datetime) -> list[str]:
        """The duration question for each written activity that just ended and has not been answered."""
        lang, lines = self.lang(), []
        for row in store.written(self.conn):
            if row["part"] != "main":
                continue
            end = datetime.fromisoformat(row["end"])
            key = f"logged:{row['group_id']}"
            asked = f"asked:{row['group_id']}"
            if end <= now < end + ASK_WINDOW and not store.was_notified(self.conn, key) \
                    and not store.was_notified(self.conn, asked):
                lines.append(tr(lang, "took_ask", kind=row["kind"], end=f"{end:%H:%M}", group=row["group_id"]))
                store.mark_notified(self.conn, asked, now)
        return lines

    # --- the week, for the dashboard --------------------------------------------------------------------------
    def week_view(self, first: date | None = None) -> dict:
        profile, now = self.profile(), self.now()
        monday = (first or now.date()) - timedelta(days=(first or now.date()).weekday())
        last = monday + timedelta(days=6)
        warnings: list[str] = []
        try:
            events, warnings = sources.fetch_range(profile, monday, last, self.home, run=self._run,
                                                   urlopen=self._urlopen)
        except sources.SourceError as exc:
            events = []
            warnings.append(tr(profile["language"], "cal_unreadable", why=exc))
        live = store.written(self.conn)
        ours = {(r["summary"], r["start"], r["end"]) for r in live}
        events = [e for e in events if (e.title, e.start.isoformat(), e.end.isoformat()) not in ours]
        wrote = [r for r in live if monday <= datetime.fromisoformat(r["start"]).date() <= last]
        pending = []
        for p in store.pending_proposals(self.conn):
            if now - datetime.fromisoformat(p["created_at"]) > PROPOSAL_LIFETIME:
                continue
            for s in p["payload"]["sessions"]:
                if monday <= date.fromisoformat(s["day"]) <= last:
                    pending.append({"proposal": p["id"], "kind": p["kind"], **s})
        shown = [{"title": e.title, "start": e.start.isoformat(), "end": e.end.isoformat(), "all_day": e.all_day}
                 for e in events]
        return {"ok": True, "week_start": monday.isoformat(), "today": now.date().isoformat(), "events": shown,
                "written": wrote, "proposed": pending, "write_enabled": self.write_enabled(), "warnings": warnings,
                "language": profile["language"]}

    def refuse(self, proposal_id: int) -> dict:
        lang = self.lang()
        proposal = store.get_proposal(self.conn, proposal_id)
        if proposal is None:
            raise UserError(tr(lang, "confirm_unknown", id=proposal_id))
        if proposal["status"] != "pending":
            raise UserError(tr(lang, "confirm_done", id=proposal_id, status=tr(lang, "status_" + proposal["status"])))
        store.set_proposal_status(self.conn, proposal_id, "refused")
        return {"ok": True, "text": tr(lang, "refused", id=proposal_id)}
