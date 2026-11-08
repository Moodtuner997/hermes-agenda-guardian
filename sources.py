"""Calendar sources: anything that yields events for one day. Nothing here writes to a calendar."""

from __future__ import annotations

import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from .model import Event
from .texts import tr

TIMEOUT = 25
MAX_ICS_BYTES = 5 * 1024 * 1024  # a secret ICS address answers with a few hundred KB; a server that goes on is cut off
GOOGLE_SCRIPT = Path("skills") / "productivity" / "google-workspace" / "scripts" / "google_api.py"
MAX_ITERATIONS = 4000


class SourceError(Exception):
    pass


def _zone(name: str):
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        return None


def to_local(value: datetime, tzname: str = "") -> datetime:
    """Naive local time. A naive input is taken as already local."""
    if value.tzinfo is None:
        return value
    zone = _zone(tzname)
    return (value.astimezone(zone) if zone else value.astimezone()).replace(tzinfo=None)


def _aware(naive: datetime, tzname: str) -> datetime:
    zone = _zone(tzname)
    return naive.replace(tzinfo=zone) if zone else naive.astimezone()


def parse_when(text: str, tzname: str = "") -> tuple[datetime, bool]:
    """ISO date or date-time -> (naive local datetime, all_day)."""
    text = text.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return datetime.combine(date.fromisoformat(text), time.min), True
    return to_local(datetime.fromisoformat(text.replace("Z", "+00:00")), tzname), False


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min)
    return start, start + timedelta(days=1)


def _json_events(data, tzname: str) -> list[Event]:
    items = data.get("events", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise SourceError("calendar JSON must be a list of events (or an object with an 'events' list)")
    events = []
    for item in items:
        if not isinstance(item, dict) or str(item.get("status", "")).lower() == "cancelled":
            continue

        def pick(key):
            value = item.get(key)
            return value.get("dateTime") or value.get("date") if isinstance(value, dict) else value

        raw_start, raw_end = pick("start"), pick("end")
        if not raw_start or not raw_end:
            continue
        try:
            start, all_day = parse_when(str(raw_start), tzname)
            end, _ = parse_when(str(raw_end), tzname)
        except ValueError:
            continue
        events.append(Event(str(item.get("summary") or item.get("title") or "(no title)"), start, end, all_day))
    return events


# --- ICS -------------------------------------------------------------------------------------------------

_WEEKDAY_CODES = {"MO": 1, "TU": 2, "WE": 3, "TH": 4, "FR": 5, "SA": 6, "SU": 7}


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def _prop(line: str) -> tuple[str, dict[str, str], str]:
    head, _, value = line.partition(":")
    name, *params = head.split(";")
    return name.upper(), {k.upper(): v for k, _, v in (p.partition("=") for p in params)}, value


def _ics_when(params: dict[str, str], value: str, tzname: str) -> tuple[datetime, bool]:
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        return datetime.strptime(value[:8], "%Y%m%d"), True
    if value.endswith("Z"):
        moment = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return to_local(moment, tzname), False
    naive = datetime.strptime(value, "%Y%m%dT%H%M%S")
    zone = _zone(params.get("TZID", ""))
    if zone:
        return to_local(naive.replace(tzinfo=zone), tzname), False
    return naive, False


def _duration(value: str) -> timedelta:
    match = re.fullmatch(r"P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", value)
    if not match:
        return timedelta(hours=1)
    weeks, days, hours, minutes, seconds = (int(g or 0) for g in match.groups())
    return timedelta(weeks=weeks, days=days, hours=hours, minutes=minutes, seconds=seconds)


def _occurrences(start: datetime, rule: dict[str, str], skip: set[date], lo: datetime, hi: datetime,
                 length: timedelta):
    """Starts of a DAILY or WEEKLY rule that touch [lo, hi). Yields naive local datetimes."""
    freq = rule.get("FREQ", "")
    interval = max(1, int(rule.get("INTERVAL", "1")))
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    until = None
    if rule.get("UNTIL"):
        until = datetime.strptime(rule["UNTIL"][:8], "%Y%m%d").date()
    byday = [_WEEKDAY_CODES[c[-2:]] for c in rule.get("BYDAY", "").split(",") if c[-2:] in _WEEKDAY_CODES]
    emitted, steps = 0, 0
    if freq == "DAILY":
        candidates = (start.date() + timedelta(days=i * interval) for i in range(MAX_ITERATIONS))
    else:
        days = sorted(byday) or [start.isoweekday()]
        monday = start.date() - timedelta(days=start.isoweekday() - 1)
        candidates = (monday + timedelta(weeks=w * interval, days=d - 1)
                      for w in range(MAX_ITERATIONS) for d in days)
    for current in candidates:
        steps += 1
        if steps > MAX_ITERATIONS:
            return
        if current < start.date():
            continue
        if until and current > until:
            return
        moment = datetime.combine(current, start.time())
        if moment >= hi:
            return
        emitted += 1
        if count is not None and emitted > count:
            return
        if current not in skip and moment + length > lo:
            yield moment


def parse_ics(text: str, day: date, tzname: str = "", warnings: list[str] | None = None,
              lang: str = "en") -> list[Event]:
    lo, hi = _day_bounds(day)
    warnings = warnings if warnings is not None else []
    events: list[Event] = []
    unsupported = 0
    body: list[str] | None = None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            body = []
        elif line == "END:VEVENT" and body is not None:
            props: dict[str, list[tuple[dict[str, str], str]]] = {}
            for entry in body:
                if ":" in entry:
                    name, params, value = _prop(entry)
                    props.setdefault(name, []).append((params, value))
            body = None
            if "DTSTART" not in props or str(props.get("STATUS", [({}, "")])[0][1]).upper() == "CANCELLED":
                continue
            try:
                start, all_day = _ics_when(*props["DTSTART"][0], tzname)
                if "DTEND" in props:
                    end, _ = _ics_when(*props["DTEND"][0], tzname)
                elif "DURATION" in props:
                    end = start + _duration(props["DURATION"][0][1])
                else:
                    end = start + (timedelta(days=1) if all_day else timedelta(hours=1))
            except ValueError:
                continue
            title = props.get("SUMMARY", [({}, "(no title)")])[0][1].replace("\\,", ",").replace("\\n", " ")
            length = end - start
            if "RRULE" in props:
                rule = dict(p.partition("=")[::2] for p in props["RRULE"][0][1].split(";"))
                if rule.get("FREQ") not in ("DAILY", "WEEKLY"):
                    unsupported += 1
                    starts = [start] if start < hi and end > lo else []
                else:
                    skip = set()
                    for params, value in props.get("EXDATE", []):
                        for part in value.split(","):
                            try:
                                skip.add(_ics_when(params, part, tzname)[0].date())
                            except ValueError:
                                pass
                    starts = list(_occurrences(start, rule, skip, lo, hi, length))
            else:
                starts = [start] if start < hi and end > lo else []
            events += [Event(title, s, s + length, all_day) for s in starts]
        elif body is not None:
            body.append(line)
    if unsupported:
        warnings.append(tr(lang, "recurring", n=unsupported))
    return events


# --- fetching --------------------------------------------------------------------------------------------

_CHILD_ENV = ("PATH", "HOME", "LANG", "TZ")
_CHILD_ENV_WINDOWS = ("SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "PATHEXT", "COMSPEC")  # no sockets without SYSTEMROOT


def _child_env(home: Path, environ=None, windows: bool | None = None) -> dict[str, str]:
    """What a calendar program starts with: the basics it needs to run and the profile folder, nothing else. The
    parent holds every provider key of Hermes; a program the user (or the Google skill) names has no use for them."""
    environ = os.environ if environ is None else environ
    keep = _CHILD_ENV + (_CHILD_ENV_WINDOWS if (os.name == "nt" if windows is None else windows) else ())
    env = {key: value for key, value in environ.items() if key in keep or key.startswith("LC_")}
    env["HERMES_HOME"] = str(home)
    return env


def _run_json(argv: list[str], run, home: Path) -> object:
    try:
        done = run(argv, capture_output=True, text=True, timeout=TIMEOUT, shell=False, env=_child_env(home))
    except FileNotFoundError:
        raise SourceError(f"calendar program not found: {argv[0]}")
    except subprocess.TimeoutExpired:
        raise SourceError(f"calendar program timed out after {TIMEOUT}s: {argv[0]}")
    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip().splitlines()
        raise SourceError(f"calendar program exited {done.returncode}: {detail[-1][:200] if detail else 'no output'}")
    try:
        return json.loads(done.stdout)
    except ValueError:
        raise SourceError("calendar program did not print JSON")


# --- an ICS address: https only, every address checked, the connection made to the checked address ------------

_NEVER_PUBLIC = [ipaddress.ip_network(net) for net in (
    "100.64.0.0/10",                      # carrier-grade NAT: where tailnet addresses live
    "192.0.0.0/24", "198.18.0.0/15",
    "::/96",                              # IPv4-compatible addresses
    "64:ff9b::/96", "64:ff9b:1::/48",     # NAT64: reaches IPv4 addresses this check never sees
    "2002::/16", "2001::/32")]            # 6to4 and Teredo, the same


def is_public(address: str) -> bool:
    """A globally routable address only: not loopback, private, link-local (169.254.169.254 is the cloud metadata
    service), CGNAT, reserved, multicast or unspecified. ``::ffff:a.b.c.d`` is judged as the IPv4 address it wraps."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if any(ip in net for net in _NEVER_PUBLIC if net.version == ip.version):
        return False
    return ip.is_global and not (ip.is_multicast or ip.is_private or ip.is_loopback or ip.is_link_local
                                 or ip.is_reserved or ip.is_unspecified)


def verified_addresses(host: str, port: int, getaddrinfo=socket.getaddrinfo) -> list[str]:
    """The addresses ``host`` resolves to, only when every one is public: a name that also answers with a private
    address could be steered there. Numeric forms (2130706433, 0x7f.1) are caught the same way, since the resolved
    address is tested, not the text. Raises URLError."""
    try:
        found = getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise urllib.error.URLError(f"cannot resolve {host}: {exc}")
    addresses = list(dict.fromkeys(info[4][0] for info in found))
    if not addresses:
        raise urllib.error.URLError(f"{host} has no address")
    for address in addresses:
        if not is_public(address):
            raise urllib.error.URLError(f"{host} resolves to {address}, which is not a public address: refused")
    return addresses


class _CheckedConnection(http.client.HTTPSConnection):
    """HTTPS to an address that was checked, the host name kept for SNI and the certificate: nothing is resolved
    again between the check and the connection, so a DNS answer that changes in between (rebinding) changes nothing."""

    def __init__(self, host, *, addresses, context, **kw):
        super().__init__(host, context=context, **kw)
        self._addresses, self._tls = addresses, context

    def connect(self):
        failure = None
        for address in self._addresses:
            try:
                sock = socket.create_connection((address, self.port), self.timeout, self.source_address)
                break
            except OSError as exc:
                failure = exc
        else:
            raise failure
        try:
            self.sock = self._tls.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


class _CheckedHTTPS(urllib.request.HTTPSHandler):
    """Resolves and checks the host of every request it opens, the first one and each redirected one."""

    def __init__(self, getaddrinfo=socket.getaddrinfo):
        super().__init__(context=ssl.create_default_context())
        self._getaddrinfo = getaddrinfo

    def https_open(self, req):
        parts = urllib.parse.urlsplit(req.full_url)
        if "\\" in parts.netloc:  # urlsplit and http.client would read the host two ways: refuse what is read twice
            raise urllib.error.URLError(f"address refused: a backslash in the host part of {parts.scheme}://{parts.netloc}")
        addresses = verified_addresses(parts.hostname or "", parts.port or 443, self._getaddrinfo)
        return self.do_open(lambda host, **kw: _CheckedConnection(host, addresses=addresses, context=self._context, **kw),
                            req)


class _SameHostRedirect(urllib.request.HTTPRedirectHandler):
    """A calendar server may send us to another path of itself, never to another host, port or scheme."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old = urllib.parse.urlsplit(req.full_url)
        new = urllib.parse.urlsplit(newurl)  # already joined to the old address by urllib
        if "\\" in new.netloc or "@" in new.netloc:  # a user-info part or a backslash: the host is read two ways
            raise urllib.error.URLError(f"redirect to {new.scheme}://{new.netloc} refused: odd characters in the host part")
        if (new.scheme != "https" or (new.hostname or "").lower() != (old.hostname or "").lower()
                or (new.port or 443) != (old.port or 443)):
            raise urllib.error.URLError(f"redirect to {new.scheme}://{new.netloc} refused: only the same https host may answer")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def build_opener(getaddrinfo=socket.getaddrinfo, https=_CheckedHTTPS) -> urllib.request.OpenerDirector:
    """Built by hand: no proxy (a proxy would be the host to check, and the connection must go to the address checked
    here), no plain http, no file or ftp handler."""
    opener = urllib.request.OpenerDirector()
    for handler in (urllib.request.UnknownHandler(), urllib.request.HTTPDefaultErrorHandler(), _SameHostRedirect(),
                    urllib.request.HTTPErrorProcessor(), https(getaddrinfo)):
        opener.add_handler(handler)
    return opener


def safe_urlopen(request, timeout=TIMEOUT, getaddrinfo=socket.getaddrinfo):
    """The default way to read an ICS address (``urlopen`` stays injectable for tests and for callers)."""
    return build_opener(getaddrinfo).open(request, timeout=timeout)


def is_url(location: str) -> bool:
    return location.lower().startswith(("http://", "https://"))


def fetch_events(profile: dict, day: date, home: Path, *, run=subprocess.run,
                 urlopen=safe_urlopen) -> tuple[list[Event], list[str]]:
    """Events touching ``day`` and warnings. Raises SourceError when the source is configured but unreadable."""
    return fetch_range(profile, day, day, home, run=run, urlopen=urlopen)


def google_argv(home: Path, *args: str) -> list[str]:
    """The Google Workspace skill's script, run with the interpreter Hermes itself runs on."""
    script = home / GOOGLE_SCRIPT
    if not script.exists():
        raise SourceError(f"Google Workspace skill not found at {script}")
    return [sys.executable, str(script), *args]


def iso_utc(moment: datetime, tzname: str) -> str:
    return _aware(moment, tzname).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_range(profile: dict, first: date, last: date, home: Path, *, run=subprocess.run,
                urlopen=safe_urlopen) -> tuple[list[Event], list[str]]:
    """Events touching the days ``first``..``last`` (both included) and warnings. A single day keeps the
    original request (100 events); a longer range asks for up to 500 and warns when the answer was cut."""
    source = profile.get("calendar") or {"type": "none"}
    kind, tzname = source.get("type", "none"), profile.get("timezone", "")
    lang = profile.get("language", "en")
    warnings: list[str] = []
    lo, hi = _day_bounds(first)[0], _day_bounds(last)[1]
    limit = 100 if first == last else 500
    if kind == "none":
        return [], [tr(lang, "no_calendar")]
    if kind in ("google", "command"):
        start_iso, end_iso = iso_utc(lo, tzname), iso_utc(hi, tzname)
        if kind == "google":
            argv = google_argv(home, "calendar", "list", "--start", start_iso, "--end", end_iso, "--max", str(limit))
        else:
            argv = [a.replace("{start}", start_iso).replace("{end}", end_iso) for a in source["argv"]]
        data = _run_json(argv, run, home)
        events = _json_events(data, tzname)
        if kind == "google" and isinstance(data, list) and len(data) >= limit and first != last:
            warnings.append(tr(lang, "range_cut", n=limit))
    elif kind == "file":
        try:
            events = _json_events(json.loads(Path(source["path"]).read_text(encoding="utf-8")), tzname)
        except (OSError, ValueError) as exc:
            raise SourceError(f"cannot read {source['path']}: {exc}")
    elif kind == "ics":
        location = source["path"]
        try:
            if is_url(location):
                if not location.lower().startswith("https://"):
                    raise SourceError(tr(lang, "ics_https_only"))
                request = urllib.request.Request(location, headers={"User-Agent": "hermes-agenda-guardian"})
                with urlopen(request, timeout=TIMEOUT) as response:
                    raw = response.read(MAX_ICS_BYTES + 1)
                if len(raw) > MAX_ICS_BYTES:
                    raise SourceError(tr(lang, "ics_too_big", mb=MAX_ICS_BYTES // (1024 * 1024)))
                text = raw.decode("utf-8", "replace")
            else:
                text = Path(location).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise SourceError(f"cannot read the ICS calendar: {exc}")
        events, seen = [], set()
        for offset in range((last - first).days + 1):
            for event in parse_ics(text, first + timedelta(days=offset), tzname, warnings, lang):
                if event not in seen:
                    seen.add(event)
                    events.append(event)
        warnings = list(dict.fromkeys(warnings))
    else:
        raise SourceError(f"unknown calendar type '{kind}'")
    events = sorted((e for e in events if e.end > lo and e.start < hi), key=lambda e: (e.start, e.end))
    return events, warnings
