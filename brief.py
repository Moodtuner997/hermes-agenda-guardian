"""Text rendering of a plan: a one-line day bar, the schedule, why each block is where it is, what drops."""

from __future__ import annotations

from datetime import datetime, timedelta

from .model import Plan

T = {
    "en": {
        "colon": ":",
        "title": "Plan for {day}",
        "summary": "{n} task(s) planned, {planned} of {free} free",
        "bar": "Day bar, 1 char = 30 min:  # task  = meeting  ~ protected  . free",
        "why": "why",
        "not_today": "Not today",
        "rules": "Rules used",
        "nothing": "Nothing planned: add tasks with /day add \"name\" 45m",
        "off": "Not a workday. Nothing planned.",
        "part": "part {i}/{n}",
        "focus": "focus",
        "now_block": "Now: {name} until {end}",
        "now_next": "Next: {name} at {start}",
        "now_none": "Nothing left in today's plan.",
        "allday": "all day",
        "nudge_start": "Starting {time}: {name} ({minutes} min{part})",
        "nudge_end": "{name} was planned until {end}. How long did it really take? Reply with the minutes "
                     "(/day done {id} <minutes>): that is how the plan learns your pace.",
    },
    "fr": {
        "colon": " :",
        "title": "Plan du {day}",
        "summary": "{n} tâche(s) planifiée(s), {planned} sur {free} de libre",
        "bar": "Barre du jour, 1 car. = 30 min :  # tâche  = réunion  ~ protégé  . libre",
        "why": "pourquoi",
        "not_today": "Pas aujourd'hui",
        "rules": "Règles appliquées",
        "nothing": "Rien de planifié : ajoute des tâches avec /day add \"nom\" 45m",
        "off": "Jour non travaillé. Rien de planifié.",
        "part": "partie {i}/{n}",
        "focus": "concentration",
        "now_block": "Maintenant : {name} jusqu'à {end}",
        "now_next": "Ensuite : {name} à {start}",
        "now_none": "Plus rien dans le plan d'aujourd'hui.",
        "allday": "toute la journée",
        "nudge_start": "Début à {time} : {name} ({minutes} min{part})",
        "nudge_end": "{name} était prévu jusqu'à {end}. Combien de temps ça a vraiment pris ? Réponds avec les "
                     "minutes (/day done {id} <minutes>) : c'est comme ça que le plan apprend ton rythme.",
    },
}

_DAYS = {
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "fr": ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."],
}


def hm(minutes: int) -> str:
    return f"{minutes // 60}h{minutes % 60:02d}" if minutes >= 60 else f"{minutes} min"


def day_bar(plan: Plan) -> str:
    if plan.window is None:
        return ""
    start, end = plan.window
    cells, cursor = [], start
    while cursor < end:
        mid = cursor + timedelta(minutes=15)
        if any(e.start <= mid < e.end and not e.all_day for e in plan.events):
            cells.append("=")
        elif any(b.start <= mid < b.end for b in plan.blocks):
            cells.append("#")
        elif any(s <= mid < e for _, s, e in plan.protected):
            cells.append("~")
        else:
            cells.append(".")
        cursor += timedelta(minutes=30)
    return f"{start.strftime('%H')} {''.join(cells)} {end.strftime('%H')}"


def render(plan: Plan, profile: dict) -> str:
    lang = profile.get("language", "en")
    t = T.get(lang, T["en"])
    day_name = _DAYS.get(lang, _DAYS["en"])[plan.day.weekday()]
    out = [t["title"].format(day=f"{day_name} {plan.day.isoformat()}")]
    for warning in plan.warnings:
        out.append(f"! {warning}")
    if plan.window is None:
        out.append(t["off"])
    else:
        count = len({b.task_id for b in plan.blocks})
        out.append(t["summary"].format(n=count, planned=hm(plan.planned_min), free=hm(plan.free_min)))
        out.append(day_bar(plan))
        out.append(t["bar"])
        rows = [(b.start, b.end, "block", b) for b in plan.blocks]
        rows += [(e.start, e.end, "event", e) for e in plan.events if not e.all_day]
        rows.sort(key=lambda r: (r[0], r[1]))
        out.append("")
        for start, end, kind, item in rows:
            span = f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}"
            if kind == "event":
                out.append(f"{span}  [=] {item.title}")
                continue
            part = f" ({t['part'].format(i=item.part, n=item.parts)})" if item.parts > 1 else ""
            out.append(f"{span}  [#] {item.name}{part}")
            out.append(f"       {t['why']}: " + "; ".join(item.why))
        for event in (e for e in plan.events if e.all_day):
            out.append(f"{t['allday']}  [=] {event.title}")
        if not plan.blocks:
            out.append(t["nothing"])
    if plan.dropped:
        out.append("")
        out.append(t["not_today"] + t["colon"])
        for item in plan.dropped:
            out.append(f"- #{item.task.id} {item.task.name}: {item.detail}")
    if plan.rules:
        out.append("")
        out.append(t["rules"] + t["colon"])
        out += [f"- {rule}" for rule in plan.rules]
    return "\n".join(out)


def render_now(plan: Plan, profile: dict, now: datetime) -> str:
    t = T.get(profile.get("language", "en"), T["en"])
    for block in plan.blocks:
        if block.start <= now < block.end:
            return t["now_block"].format(name=block.name, end=block.end.strftime("%H:%M"))
    upcoming = [b for b in plan.blocks if b.start > now]
    if upcoming:
        return t["now_next"].format(name=upcoming[0].name, start=upcoming[0].start.strftime("%H:%M"))
    return t["now_none"]
