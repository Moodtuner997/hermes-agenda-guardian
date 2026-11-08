"""The pre_tool_call guard: the obvious side roads to the calendar source (the CLI, the package's own functions, its
folders) ask a human, or are refused in a cron run where nobody can answer. Every route pairs a refused case with a
case that goes through. The guard is not a security boundary: what it cannot see is listed in the last test."""

import pytest

import agenda_guardian as ag
from agenda_guardian import guard

from conftest import ROOT
from test_commands import Ctx

HOME = "/home/hermes/.hermes"
ROUTES = [  # (tool, arguments, route)
    ("terminal", {"command": "hermes guardian set calendar=cmd:mycal"}, "calendar"),
    ("terminal", {"command": "hermes -p work guardian set Calendar=none"}, "calendar"),
    ("terminal", {"command": f"sudo -u hermes {HOME}/../.local/bin/hermes guardian setup auto"}, "calendar"),
    ("terminal", {"command": 'cd /tmp && hermes guardian set work_hours=09:00-17:00 "calendar=ics:http://x/a.ics"'},
     "calendar"),
    ("terminal", {"command": "HERMES_HOME=/tmp/h python hermes_cli/main.py guardian set calendar=google"}, "calendar"),
    ("execute_code", {"code": 'import subprocess\nsubprocess.run(["hermes", "guardian", "set", "calendar=cmd:x"])'},
     "calendar"),
    ("execute_code", {"code": "from agenda_guardian.profile import apply_setting\napply_setting(p, 'calendar', 'x')"},
     "code"),
    ("terminal", {"command": "python -c 'g.set_rules([(\"calendar\", \"cmd:x\")])'"}, "code"),
    ("terminal", {"command": "python -c 'g.setup_auto()'"}, "code"),
    ("terminal", {"command": f"sqlite3 {HOME}/plugin-data/agenda-guardian/guardian.db 'update profile set v=1'"}, "storage"),
    ("terminal", {"command": r"copy x C:\Users\me\AppData\Local\hermes\plugin-data\agenda-guardian\guardian.db"}, "storage"),
    ("terminal", {"command": "ls", "workdir": f"{HOME}/plugins/agenda-guardian"}, "storage"),
    ("execute_code", {"code": 'open(os.path.join(home, "plugin-data", "agenda-guardian", "guardian.db"), "wb")'}, "storage"),
    ("write_file", {"path": f"{HOME}/plugins/agenda-guardian/sources.py", "content": "x"}, "storage"),
    ("write_file", {"path": f"{HOME}/plugin-data/agenda-guardian/guardian.db", "content": "x"}, "storage"),
    ("patch", {"path": r"C:\Users\me\.hermes\PLUGINS\Agenda-Guardian\core.py", "old_string": "a", "new_string": "b"},
     "storage"),
    ("patch", {"mode": "patch", "patch": "*** Begin Patch\n*** Update File: plugins/agenda-guardian/core.py\n*** End Patch"},
     "storage"),
    # the same road in other obvious spellings: quoted key, line continuations of three shells, a scripts file
    ("terminal", {"command": "hermes guardian set 'calendar'=cmd:x"}, "calendar"),
    ("terminal", {"command": 'hermes guardian set "calendar"="cmd:x"'}, "calendar"),
    ("terminal", {"command": "hermes guardian \\\n  set calendar=cmd:x"}, "calendar"),
    ("terminal", {"command": "hermes guardian ^\n set calendar=cmd:x"}, "calendar"),
    ("terminal", {"command": "hermes guardian setup \\\n auto"}, "calendar"),
    ("write_file", {"path": f"{HOME}/scripts/agenda-guardian-nudge.py", "content": "print(1)"}, "storage"),
    # a one-character escape the shell drops: bash \, cmd.exe ^ (ticket 8)
    ("terminal", {"command": r"hermes guardian set calendar\=cmd:x"}, "calendar"),
    ("terminal", {"command": "hermes guardian set calendar^=cmd:x"}, "calendar"),
    ("terminal", {"command": r"hermes guardian s\et calendar=cmd:x"}, "calendar"),
    ("terminal", {"command": r"hermes g\uardian set \calendar=cmd:x"}, "calendar"),
    ("terminal", {"command": r"hermes guardian set 'calendar'\=cmd:x"}, "calendar"),
    ("terminal", {"command": r"hermes guardian setup au\to"}, "calendar"),
    ("terminal", {"command": r"ls plugin\-data/agenda-guardian"}, "storage"),
    ("terminal", {"command": r"cat plugins/agenda\-guardian/README.md"}, "storage"),
]
THROUGH = [
    ("terminal", {"command": "hermes guardian plan"}),
    ("terminal", {"command": "hermes guardian set work_hours=09:00-17:00 buffer_min=5"}),
    ("terminal", {"command": "hermes guardian setup"}),
    ("terminal", {"command": "hermes plugins update agenda-guardian"}),
    ("terminal", {"command": "echo hermes guardian is a planner"}),
    ("terminal", {"command": "git commit -m 'guardian: set the buffer'"}),
    ("terminal", {"command": "ls", "workdir": "/home/me/project"}),
    ("execute_code", {"code": "print(1 + 1)"}),
    ("write_file", {"path": "/home/me/notes.md", "content": "plugin-data/agenda-guardian is where the planner keeps data"}),
    ("patch", {"path": "/home/me/project/app.py", "old_string": "a", "new_string": "b"}),
    ("read_file", {"path": f"{HOME}/plugins/agenda-guardian/README.md"}),  # reading is not watched
    ("search_files", {"pattern": "guardian", "path": f"{HOME}/plugin-data/agenda-guardian"}),
    ("day_setup", {"settings": {"calendar": "cmd:x"}}),  # the plugin's own tool refuses it itself
    ("day_schedule", {"action": "on"}),
    ("cronjob_manage", {"action": "create", "script": "agenda-guardian-nudge.py", "name": "agenda-guardian-nudge"}),
    # ordinary work that only shares a word with the plugin
    ("terminal", {"command": "grep -rn save_profile src/"}),
    ("terminal", {"command": "git log --grep=apply_setting"}),
    ("execute_code", {"code": "firewall.set_rules(rules)"}),
    ("terminal", {"command": r"cd C:\src\hermes-plugins\agenda-guardian && git status"}),
    ("terminal", {"command": "git status", "workdir": "/home/me/hermes-plugins/agenda-guardian"}),
    # an escape that is not in front of the calendar key does not make a road
    ("terminal", {"command": r"hermes guardian set work_hours=09:00-17:00 buffer_min\=5"}),
    ("terminal", {"command": "hermes guardian set work_hours^=09:00-17:00"}),
    ("terminal", {"command": r"cd C:\src\hermes-plugins\agenda-guardian\tests && dir"}),
    ("terminal", {"command": r"echo 5^2 and a\=b"}),
]


@pytest.fixture(autouse=True)
def outside_cron(monkeypatch):
    monkeypatch.delenv("HERMES_CRON_SESSION", raising=False)


@pytest.mark.parametrize("tool,args,road", ROUTES)
def test_each_obvious_road_asks_a_human_with_the_exact_call(tool, args, road):
    directive = guard.check(tool, args)
    assert directive["action"] == "approve", directive
    assert directive["rule_key"].startswith(f"agenda-guardian:{road}:"), directive["rule_key"]
    shown = args.get("command") or args.get("code") or args.get("path") or args["patch"]
    assert shown.strip()[:300] in directive["message"] and tool in directive["message"]
    assert "Allow it only if you asked for it" in directive["message"] and "Autorise seulement" in directive["message"]


@pytest.mark.parametrize("tool,args", THROUGH)
def test_everything_else_goes_through(tool, args):
    assert guard.check(tool, args) is None


@pytest.mark.parametrize("tool,args,road", ROUTES)
def test_in_a_cron_run_nobody_can_answer_so_it_is_refused_without_naming_the_road(monkeypatch, tool, args, road):
    monkeypatch.setenv("HERMES_CRON_SESSION", "1")
    directive = guard.check(tool, args)
    assert directive["action"] == "block" and directive["message"]
    assert "hermes guardian" not in directive["message"] and "/day" not in directive["message"]
    assert "terminal" not in directive["message"]


def test_a_cron_run_still_lets_the_innocent_calls_through(monkeypatch):
    monkeypatch.setenv("HERMES_CRON_SESSION", "1")
    assert all(guard.check(tool, args) is None for tool, args in THROUGH)


def test_the_approval_rule_is_one_per_exact_call_never_plugin_wide():
    key = lambda tool, args: guard.check(tool, args)["rule_key"]
    keys = {key("terminal", {"command": f"hermes guardian set calendar=cmd:prog{i}"}) for i in range(5)}
    assert len(keys) == 5
    call = {"command": "hermes guardian set calendar=cmd:prog"}
    assert key("terminal", call) == key("terminal", dict(call))  # the same call is the same rule
    # another spelling, another list, another content: another rule, so one "always" never covers a different call
    assert len({key("terminal", call), key("terminal", {"command": "hermes guardian set  calendar=cmd:prog"}),
                key("terminal", {"command": "hermes guardian set calendar=cmd:prog,arg"}),
                key("terminal", {"command": "hermes guardian set calendar=cmd:prog arg"}),
                key("terminal", {"command": "hermes guardian set calendar=cmd:prog(arg)"})}) == 5
    path = f"{HOME}/plugin-data/agenda-guardian/x"
    assert key("write_file", {"path": path, "content": '{"calendar": "google"}'}) != key(
        "write_file", {"path": path, "content": '{"calendar": "cmd:evil.sh"}'})
    patch = {"path": f"{HOME}/plugins/agenda-guardian/core.py", "old_string": "a", "new_string": "b"}
    assert key("patch", patch) != key("patch", {**patch, "new_string": "c"})
    assert all(k.count(":") == 2 and len(k.split(":")[2]) == 12 for k in keys)


def test_what_would_be_written_is_shown_to_the_human():
    path = f"{HOME}/plugin-data/agenda-guardian/x"
    message = guard.check("write_file", {"path": path, "content": '{"calendar": "cmd:evil.sh"}'})["message"]
    assert path in message and "[content]" in message and "cmd:evil.sh" in message
    message = guard.check("patch", {"path": f"{HOME}/plugins/agenda-guardian/core.py", "old_string": "x = 1",
                                    "new_string": "x = evil()"})["message"]
    assert "[old_string] x = 1" in message and "[new_string] x = evil()" in message
    message = guard.check("write_file", {"path": path, "content": "z" * 500})["message"]
    assert "z" * 200 in message and "z" * 201 not in message and "[…]" in message


def test_a_long_call_cannot_hide_the_matching_part_past_the_cut():
    road = 'os.system("hermes guardian set calendar=cmd:evil.sh")'
    long_code = "import os\n" + "# padding\n" * 80 + road
    message = guard.check("execute_code", {"code": long_code})["message"]
    assert "cmd:evil.sh" in message and message.count("# padding") < 80
    second = "hermes guardian set calendar=google" + " " * 400 + "; hermes guardian set calendar=cmd:evil.sh"
    message = guard.check("terminal", {"command": second})["message"]
    assert "calendar=google" in message and "cmd:evil.sh" in message
    short = {"command": "hermes guardian set calendar=cmd:mycal"}
    assert guard.check("terminal", short)["message"].count("hermes guardian set calendar=cmd:mycal") == 2  # en + fr


LONG = {  # about 260 KB each
    "hermes-words": "hermes " * 35000, "hermes-dots": "hermes." * 35000, "guardian-plan": "hermes guardian plan " * 12000,
    "guardian-set": "hermes guardian set " * 12000,
    "imports": "".join(f"from hermes_cli.m{i} import t{i}\n" for i in range(9000)),
    "guardian-then-hermes": "guardian " + "hermes " * 35000, "guardian-then-dots": "guardian " + "hermes." * 35000,
    "road-at-the-end": "hermes " * 20000 + "hermes guardian set calendar=cmd:x", "plugins-words": "plugins/" * 30000,
    "plugins-slashes": "plugins" + "/" * 200000,
    "escapes": "\\^" * 130000, "escaped-words": "hermes\\ guardian\\ " * 14000,
    "escaped-road-at-the-end": "\\^hermes " * 16000 + "hermes guardian set calendar\\=cmd:x",
}


@pytest.mark.parametrize("raw", LONG.values(), ids=LONG.keys())
def test_a_very_long_call_is_matched_in_a_fraction_of_a_second(raw):
    """Hermes blocks a pre_tool_call that overruns its timeout and re holds the GIL, so a quadratic pattern would
    freeze every tool (measured on the first 0.5.2 patterns: 3 s at 78 KB, 67 s at 260 KB; now 0.6 s at worst)."""
    import time

    for tool, field in (("terminal", "command"), ("execute_code", "code"), ("patch", "patch")):
        started = time.perf_counter()
        guard.check(tool, {field: raw})
        assert time.perf_counter() - started < 5.0, (tool, raw[:30])  # 0.6 s worst measured; the old patterns took minutes
    assert guard.check("terminal", {"command": "hermes " * 20000 + "hermes guardian set calendar=cmd:x"})["action"] == "approve"
    assert guard.check("terminal", {"command": LONG["escaped-road-at-the-end"]})["action"] == "approve"


def test_the_hook_is_registered_declared_and_cannot_stop_the_agent_when_it_fails(monkeypatch):
    ctx = Ctx()
    ag.register(ctx)
    assert set(ctx.hooks) == {"pre_gateway_dispatch", "pre_tool_call"}
    declared = [line.strip()[2:] for line in (ROOT / "plugin.yaml").read_text(encoding="utf-8").split("provides_hooks:")[1]
                .splitlines() if line.strip().startswith("- ")]
    assert set(declared) == set(ctx.hooks)
    assert ctx.hooks["pre_tool_call"](tool_name="terminal", args={"command": "hermes guardian set calendar=cmd:x"},
                                      task_id="t", tool_call_id="c", turn_id="u")["action"] == "approve"
    assert ctx.hooks["pre_tool_call"](tool_name="terminal", args={"command": "echo ok"}, task_id="t") is None

    def broken(*_a, **_k):
        raise RuntimeError("matcher bug")

    monkeypatch.setattr(guard, "check", broken)
    assert ctx.hooks["pre_tool_call"](tool_name="terminal", args={"command": "hermes guardian set calendar=cmd:x"}) is None


def test_a_register_hook_that_refuses_the_name_does_not_stop_the_plugin_loading():
    class Old(Ctx):
        def register_hook(self, name, callback, **kw):
            if name == "pre_tool_call":
                raise ValueError("unknown hook")
            super().register_hook(name, callback, **kw)

    ctx = Old()
    ag.register(ctx)
    assert set(ctx.hooks) == {"pre_gateway_dispatch"} and "day_setup" in ctx.tools


def test_what_the_guard_cannot_see_is_not_pretended_to_be_closed():
    """Documented limit (README): a call that hides what it does is not recognised. This test pins the limit, so a
    change that starts catching these is a deliberate one, and the README's list stays honest."""
    hidden = [
        ("terminal", {"command": "echo aGVybWVzIGd1YXJkaWFuIHNldCBjYWxlbmRhcj1jbWQ6eA== | base64 -d | sh"}),
        ("terminal", {"command": "g=guard; hermes ${g}ian set calendar=cmd:x"}),
        ("execute_code", {"code": "p = 'plugin' + '-data/agenda' + '-guardian'; open(p + '/gu' + 'ardian.db', 'wb')"}),
        # written first, run later: the content of a file is shown to the human but not scanned
        ("write_file", {"path": "/tmp/x.sh", "content": "hermes guardian set calendar=cmd:x"}),
        ("terminal", {"command": "ls", "workdir": f"{HOME}/plugins/./agenda-guardian"}),
    ]
    assert all(guard.check(tool, args) is None for tool, args in hidden)
