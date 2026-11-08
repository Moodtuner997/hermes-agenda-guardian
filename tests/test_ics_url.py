"""An ICS address is read over https only, from an address that was checked, and a redirect may not leave the host.
Nothing here touches the network: names are resolved by a fake, and a refused host must never open a socket."""

import io
import socket
import urllib.error
import urllib.parse
import urllib.request
import urllib.response
from email.message import Message
from types import SimpleNamespace

import pytest

from agenda_guardian import profile as prof, sources
from agenda_guardian.sources import is_public, verified_addresses

from conftest import MONDAY

PUBLIC = "93.184.216.34"
NOT_PUBLIC = [
    "127.0.0.1", "127.1.2.3", "::1", "10.0.0.5", "172.16.0.1", "172.31.255.255", "192.168.1.1", "169.254.169.254",
    "169.254.0.1", "fe80::1", "fe80::1%eth0", "100.64.0.1", "100.127.255.254", "0.0.0.0", "::", "0.1.2.3", "224.0.0.1",
    "ff02::1", "240.0.0.1", "255.255.255.255", "192.0.0.1", "198.18.0.1", "198.19.255.255", "fc00::1", "fd12:3456::1",
    "::ffff:127.0.0.1", "::ffff:10.0.0.1", "::ffff:169.254.169.254", "::ffff:100.64.0.1", "::ffff:7f00:1", "::7f00:1",
    "64:ff9b::a00:1", "2002:7f00:1::", "2001:0:4136:e378:8000:63bf:3fff:fdd2", "192.0.2.1", "2001:db8::1",
    "not-an-address", ""]
GLOBAL = ["93.184.216.34", "8.8.8.8", "1.1.1.1", "2606:4700:4700::1111", "2a00:1450:4007:80f::200e", "::ffff:8.8.8.8",
          "100.63.255.255", "100.128.0.1", "172.15.255.255", "172.32.0.1", "11.0.0.1"]


def answers(*addresses):
    """A getaddrinfo that answers these addresses for any name, and counts how often it was asked."""
    def getaddrinfo(host, port, **kw):
        getaddrinfo.asked.append(host)
        return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in addresses]

    getaddrinfo.asked = []
    return getaddrinfo


@pytest.fixture
def no_socket(monkeypatch):
    """A refused host must never open a connection: any socket opened here fails the test."""
    def refuse(*a, **kw):
        pytest.fail(f"a socket was opened: {a}")

    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.mark.parametrize("address", NOT_PUBLIC)
def test_an_address_that_is_not_public_is_refused(address):
    assert is_public(address) is False


@pytest.mark.parametrize("address", GLOBAL)
def test_a_public_address_is_accepted(address):
    assert is_public(address) is True


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.5", "169.254.169.254", "100.64.0.1", "::1", "::ffff:127.0.0.1"])
def test_a_name_resolving_to_a_private_address_is_refused(address):
    with pytest.raises(urllib.error.URLError, match="not a public address"):
        verified_addresses("calendar.example", 443, answers(address))


def test_one_private_answer_among_public_ones_is_enough_to_refuse():
    with pytest.raises(urllib.error.URLError, match="10.0.0.5"):
        verified_addresses("calendar.example", 443, answers(PUBLIC, "10.0.0.5"))


def test_public_answers_are_returned_without_duplicates():
    assert verified_addresses("calendar.example", 443, answers(PUBLIC, "2606:4700:4700::1111", PUBLIC)) == [
        PUBLIC, "2606:4700:4700::1111"]


def test_a_name_that_does_not_resolve_is_an_error():
    def getaddrinfo(host, port, **kw):
        raise socket.gaierror(11001, "no such host")

    with pytest.raises(urllib.error.URLError, match="cannot resolve"):
        verified_addresses("nowhere.invalid", 443, getaddrinfo)
    with pytest.raises(urllib.error.URLError, match="no address"):
        verified_addresses("empty.example", 443, lambda *a, **kw: [])


@pytest.mark.parametrize("literal", ["127.0.0.1", "::1", "169.254.169.254", "10.0.0.5", "100.64.0.1"])
def test_a_numeric_host_is_tested_through_the_real_resolver_too(literal):
    """Known bad with the system resolver itself: an address literal needs no network to resolve."""
    with pytest.raises(urllib.error.URLError, match="not a public address"):
        verified_addresses(literal, 443)


@pytest.mark.parametrize("url, resolved", [
    ("https://127.0.0.1/a.ics", "127.0.0.1"),
    ("https://localhost/a.ics", "127.0.0.1"),
    ("https://[::1]/a.ics", "::1"),
    ("https://10.0.0.5/a.ics", "10.0.0.5"),
    ("https://169.254.169.254/latest/meta-data", "169.254.169.254"),
    ("https://100.64.0.1/a.ics", "100.64.0.1"),
    ("https://[::ffff:127.0.0.1]/a.ics", "::ffff:127.0.0.1"),
    ("https://2130706433/a.ics", "127.0.0.1"),                    # the numeric form of 127.0.0.1
    ("https://calendar.example/a.ics", "172.16.9.9"),             # a name pointing inside the network
])
def test_the_default_opener_refuses_these_hosts_without_opening_a_socket(url, resolved, no_socket):
    getaddrinfo = answers(resolved)
    with pytest.raises(urllib.error.URLError, match="not a public address"):
        sources.safe_urlopen(urllib.request.Request(url), 3, getaddrinfo)
    assert len(getaddrinfo.asked) == 1


def test_the_default_opener_refuses_plain_http_and_other_schemes(no_socket):
    for url in ("http://calendar.example/a.ics", "ftp://calendar.example/a.ics", "file:///etc/passwd"):
        with pytest.raises(urllib.error.URLError):
            sources.safe_urlopen(urllib.request.Request(url), 3, answers(PUBLIC))


def test_the_opener_has_no_proxy_plain_http_file_or_ftp_handler():
    kinds = {type(handler).__name__ for handler in sources.build_opener().handlers}
    assert not kinds & {"ProxyHandler", "HTTPHandler", "FileHandler", "FTPHandler", "DataHandler"}
    assert "_CheckedHTTPS" in kinds and "_SameHostRedirect" in kinds


class FakeContext:
    def __init__(self, fail=False):
        self.fail, self.server_hostname = fail, None

    def wrap_socket(self, sock, server_hostname=None):
        self.server_hostname = server_hostname
        if self.fail:
            raise OSError("handshake failed")
        return sock


class FakeSocket:
    closed = False

    def close(self):
        self.closed = True


def test_the_connection_goes_to_the_checked_address_and_keeps_the_name_for_the_certificate(monkeypatch):
    opened = []
    monkeypatch.setattr(socket, "create_connection", lambda addr, timeout, source: opened.append((addr, timeout)) or FakeSocket())
    context = FakeContext()
    connection = sources._CheckedConnection("calendar.example", addresses=[PUBLIC], context=context, timeout=7)
    connection.connect()
    assert opened == [((PUBLIC, 443), 7)] and context.server_hostname == "calendar.example"


def test_the_next_checked_address_is_tried_when_the_first_does_not_answer(monkeypatch):
    opened = []

    def create(addr, timeout, source):
        opened.append(addr[0])
        if addr[0] == PUBLIC:
            raise OSError("unreachable")
        return FakeSocket()

    monkeypatch.setattr(socket, "create_connection", create)
    connection = sources._CheckedConnection("calendar.example:8443", addresses=[PUBLIC, "8.8.8.8"],
                                            context=FakeContext(), timeout=3)
    connection.connect()
    assert opened == [PUBLIC, "8.8.8.8"] and connection.port == 8443
    monkeypatch.setattr(socket, "create_connection", lambda *a: (_ for _ in ()).throw(OSError("down")))
    with pytest.raises(OSError, match="down"):
        sources._CheckedConnection("calendar.example", addresses=[PUBLIC], context=FakeContext(), timeout=3).connect()


def test_a_failed_handshake_closes_the_socket(monkeypatch):
    sock = FakeSocket()
    monkeypatch.setattr(socket, "create_connection", lambda *a: sock)
    with pytest.raises(OSError, match="handshake"):
        sources._CheckedConnection("calendar.example", addresses=[PUBLIC], context=FakeContext(fail=True),
                                   timeout=3).connect()
    assert sock.closed


def test_the_name_is_resolved_once_and_the_connection_uses_that_answer(monkeypatch):
    """Rebinding: the second answer of the DNS (a private address) must never be used."""
    getaddrinfo = answers(PUBLIC)
    handler = sources._CheckedHTTPS(getaddrinfo)
    captured = {}
    monkeypatch.setattr(handler, "do_open", lambda factory, req: captured.update(factory=factory) or "response")
    assert handler.https_open(urllib.request.Request("https://calendar.example/a.ics")) == "response"
    getaddrinfo_after = answers("127.0.0.1")  # what the DNS says from now on
    opened = []
    monkeypatch.setattr(socket, "create_connection", lambda addr, timeout, source: opened.append(addr) or FakeSocket())
    connection = captured["factory"]("calendar.example", timeout=5)
    connection._tls = FakeContext()
    connection.connect()
    assert opened == [(PUBLIC, 443)] and getaddrinfo.asked == ["calendar.example"] and getaddrinfo_after.asked == []


def redirect(req_url, location, code=302):
    """What urllib asks of the handler: the Location, already joined to the address it came from."""
    handler = sources._SameHostRedirect()
    joined = urllib.parse.urljoin(req_url, location)
    return handler.redirect_request(urllib.request.Request(req_url), None, code, "Found", Message(), joined)


@pytest.mark.parametrize("location", [
    "https://evil.example/a.ics",                 # another host
    "http://calendar.example/a.ics",              # downgrade to plain http
    "https://calendar.example:8443/a.ics",        # another port of the same host
    "//evil.example/a.ics",                       # protocol-relative
    "https://127.0.0.1/a.ics",
    "ftp://calendar.example/a.ics",
    "https://calendar.example.evil.example/a.ics",
])
def test_a_redirect_to_another_host_port_or_scheme_is_refused(location):
    with pytest.raises(urllib.error.URLError, match="refused"):
        redirect("https://calendar.example/a.ics", location)


@pytest.mark.parametrize("location, expected", [
    ("/other/b.ics", "https://calendar.example/other/b.ics"),
    ("b.ics", "https://calendar.example/b.ics"),
    ("https://calendar.example/c.ics", "https://calendar.example/c.ics"),
    ("https://CALENDAR.example:443/d.ics", "https://CALENDAR.example:443/d.ics"),
])
def test_a_redirect_to_the_same_host_is_followed(location, expected):
    assert redirect("https://calendar.example/a.ics", location).full_url == expected


class Hops(sources._CheckedHTTPS):
    """The real handler with the connection replaced by canned answers: the host check of each hop still runs."""
    script: list

    def do_open(self, factory, req):
        self.script.hops.append(req.full_url)
        status, location = self.script.answers.pop(0)
        headers = Message()
        if location:
            headers["Location"] = location
        response = urllib.response.addinfourl(io.BytesIO(b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"), headers,
                                              req.full_url, status)
        response.msg = "Found" if location else "OK"
        return response


def run_hops(answers_list, dns):
    script = SimpleNamespace(hops=[], answers=list(answers_list))
    Hops.script = script
    opener = sources.build_opener(dns, https=Hops)
    return opener.open(urllib.request.Request("https://calendar.example/a.ics"), timeout=3), script


def test_a_redirect_to_the_same_host_is_followed_and_its_address_checked_again():
    dns = answers(PUBLIC)
    response, script = run_hops([(302, "/b.ics"), (200, None)], dns)
    assert response.code == 200 and script.hops == ["https://calendar.example/a.ics", "https://calendar.example/b.ics"]
    assert dns.asked == ["calendar.example", "calendar.example"]  # each hop resolves and checks the host again


def test_the_second_hop_is_refused_when_the_name_now_points_inside():
    state = {"calls": 0}

    def rebinding(host, port, **kw):
        state["calls"] += 1
        return answers(PUBLIC if state["calls"] == 1 else "169.254.169.254")(host, port)

    with pytest.raises(urllib.error.URLError, match="169.254.169.254"):
        run_hops([(302, "/b.ics"), (200, None)], rebinding)
    assert state["calls"] == 2


def test_a_redirect_to_another_host_is_refused_by_the_opener():
    with pytest.raises(urllib.error.URLError, match="only the same https host"):
        run_hops([(302, "https://evil.example/a.ics")], answers(PUBLIC))


@pytest.mark.parametrize("location", [
    "https://evil.example\\@calendar.example/x",   # urlsplit says calendar.example, http.client gets the whole netloc
    "https://user@calendar.example/x",             # a user-info part
    "https://calendar.example\\.evil.example/x",
    "https://calendar.example\\/x",
])
def test_a_redirect_whose_host_part_is_read_two_ways_is_refused(location):
    with pytest.raises(urllib.error.URLError, match="odd characters"):
        redirect("https://calendar.example/a.ics", location)


def test_a_backslash_in_the_host_part_of_an_address_is_refused_before_any_name_is_resolved(no_socket):
    dns = answers(PUBLIC)
    with pytest.raises(urllib.error.URLError, match="backslash"):
        run_hops_from("https://evil.example\\@calendar.example/a.ics", [(200, None)], dns)
    assert dns.asked == []


@pytest.mark.parametrize("location", [
    "https://evil.example%5C@calendar.example/x",  # the backslash percent-encoded: urlsplit keeps it, http.client decodes it
    "https://evil.example%5c@calendar.example/x",
    "https://calendar.example:443%5C/x",
])
def test_a_percent_encoded_backslash_in_a_redirect_host_part_is_refused(location):
    with pytest.raises(urllib.error.URLError, match="refused"):
        redirect("https://calendar.example/a.ics", location)


@pytest.mark.parametrize("location", ["https://calendar.example:44%33/a.ics", "https://calendar.example:abc/a.ics",
                                      "https://calendar.example:99999/a.ics"])
def test_a_port_that_is_not_a_port_is_a_refusal_not_a_crash(location):
    with pytest.raises(urllib.error.URLError, match="refused"):
        redirect("https://calendar.example/a.ics", location)
    dns = answers(PUBLIC)
    with pytest.raises(urllib.error.URLError, match="not a number"):
        run_hops_from(location, [(200, None)], dns)
    assert dns.asked == []


def test_a_percent_encoded_backslash_in_the_first_address_is_refused_before_any_name_is_resolved(no_socket):
    dns = answers(PUBLIC)
    with pytest.raises(urllib.error.URLError, match="backslash"):
        run_hops_from("https://evil.example%5C@calendar.example/a.ics", [(200, None)], dns)
    assert dns.asked == []


def run_hops_from(url, answers_list, dns):
    Hops.script = SimpleNamespace(hops=[], answers=list(answers_list))
    return sources.build_opener(dns, https=Hops).open(urllib.request.Request(url), timeout=3)


def test_the_calendar_rule_refuses_plain_http_when_it_is_set_and_keeps_https(profile):
    for typed in ("ics:http://calendar.example/a.ics", "ics:HTTP://calendar.example/a.ics"):
        with pytest.raises(ValueError, match="must start with https://"):
            prof.apply_setting(profile, "calendar", typed, MONDAY)
    assert profile["calendar"] == {"type": "none"}
    prof.apply_setting(profile, "calendar", "ics:HTTPS://calendar.example/a.ics", MONDAY)
    assert profile["calendar"] == {"type": "ics", "path": "HTTPS://calendar.example/a.ics"}


def test_every_real_entry_point_uses_the_hardened_opener(make_guardian):
    import inspect

    assert inspect.signature(sources.fetch_range).parameters["urlopen"].default is sources.safe_urlopen
    assert inspect.signature(sources.fetch_events).parameters["urlopen"].default is sources.safe_urlopen
    assert make_guardian()._urlopen is sources.safe_urlopen
