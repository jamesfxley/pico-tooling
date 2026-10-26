# SPDX-License-Identifier: MIT
"""Socket client and sequencing without devices (AR-12, AR-13, AR-15)."""

import contextlib
import dataclasses
import io
import ipaddress
import json
import secrets
import socket
import socketserver
import threading
from pathlib import Path

import pytest

from pico_tooling import device
from pico_tooling.__main__ import parser
from pico_tooling.device_errors import CANNOT_TRY, RefusalError
from pico_tooling.device_proxy import CONNECTION_FILE, Proxy, find_connection

SERIAL = "TEST-BOARD"


class FakeProxy(socketserver.ThreadingTCPServer):
    """Protocol-faithful peer; it never enumerates or opens a device."""

    daemon_threads = False

    def __init__(self, root):
        super().__init__(("127.0.0.1", 0), Handler)
        self.root = root
        self.token = secrets.token_hex(16)
        self.allowed = True
        self.stage = "application"
        self.reset = True
        self.reset_error = None
        self.reconnect = True
        self.fail_load = False
        self.chunks = [b"boot: ", b"ready\n"]
        self.requests = []
        self.typed = []
        self.protocol_error = None
        self.disconnect = False

    def boards(self):
        if self.stage == "absent":
            return []
        return [
            {
                "serial": SERIAL,
                "ports": ["COM7"] if self.stage == "application" else [],
                "bootloader": self.stage == "bootloader",
                "listed": self.allowed,
                "drive": "X:" if self.stage == "bootloader" else None,
            },
        ]


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        connection = self.request
        connection.settimeout(1)
        line = bytearray()
        while not line.endswith(b"\n"):
            chunk = connection.recv(1)
            if not chunk:
                return
            line += chunk
        request = json.loads(line)
        peer = self.server
        peer.requests.append(request)
        if request.get("token") != peer.token:
            self.reply(ok=False, code="token", error="bad token")
            return
        if peer.protocol_error:
            connection.sendall(peer.protocol_error)
            return
        self.dispatch(request)

    def dispatch(self, request):
        peer = self.server
        cmd = request["cmd"]
        if cmd == "list":
            self.reply(ok=True, boards=peer.boards())
        elif cmd == "allowed":
            self.reply(ok=True, allowed=peer.allowed and request["serial"] == SERIAL)
        elif not peer.allowed or request["serial"] != SERIAL:
            self.reply(ok=False, code="denied", error="not in host allow-list")
        elif cmd == "load":
            self.load(request)
        elif cmd == "open":
            self.open_stream(request)
        else:
            self.reply(ok=False, code="request", error="unknown command")

    def load(self, request):
        peer = self.server
        path = Path(request["path"])
        resolved = (peer.root / path).resolve()
        if (
            path.is_absolute()
            or not resolved.is_relative_to(peer.root)
            or not resolved.is_file()
        ):
            self.reply(ok=False, code="path", error="not inside the workspace")
        elif peer.fail_load:
            self.reply(ok=False, code="failed", error="copy failed")
        else:
            peer.stage = "application" if peer.reconnect else "bootloader"
            self.reply(ok=True)

    def reset_stream(self):
        peer = self.server
        if peer.reset_error:
            if peer.reset_error in {"failed", "absent", "closed"} and peer.reset:
                peer.stage = "bootloader"
            if peer.reset_error != "closed":
                self.reply(ok=False, code=peer.reset_error, error="reset open refused")
            return
        self.reply(ok=True)
        while self.request.recv(1024):
            pass
        if peer.reset:
            peer.stage = "bootloader"

    def open_stream(self, request):
        peer = self.server
        connection = self.request
        if request["baud"] == 1200:
            self.reset_stream()
            return
        self.reply(ok=True)
        for chunk in peer.chunks:
            connection.sendall(chunk)
        if peer.disconnect:
            peer.stage = "absent"
            return
        try:
            chunk = connection.recv(1024)
            if chunk:
                peer.typed.append(chunk)
        except TimeoutError:
            return

    def reply(self, **fields):
        self.request.sendall(json.dumps(fields).encode() + b"\n")


@pytest.fixture(autouse=True)
def proxy_search_root(tmp_path):
    """Bound every device test to its temporary root (AR-15, EN-04.1).

    The real parser stops at invalid metadata. A root sentinel prevents ancestor
    discovery without mocking that parser or changing production behavior.
    Tests with a proxy replace it with their own explicit connection metadata.
    """
    (tmp_path / CONNECTION_FILE).write_text("{}")


@pytest.fixture
def proxy(tmp_path):
    with FakeProxy(tmp_path) as peer:
        (tmp_path / CONNECTION_FILE).write_text(
            json.dumps(
                {
                    "host": peer.server_address[0],
                    "port": peer.server_address[1],
                    "token": peer.token,
                },
            ),
        )
        (tmp_path / "image.uf2").write_bytes(b"fixture")
        (tmp_path / "CMakeCache.txt").write_text("CMAKE_BUILD_TYPE:STRING=Release\n")
        thread = threading.Thread(
            target=peer.serve_forever,
            kwargs={"poll_interval": 0.01},
        )
        thread.start()
        try:
            yield peer
        finally:
            peer.shutdown()
            thread.join(timeout=5)


def host_of(peer):
    return device.Host(
        cwd=peer.root,
        stdin=None,
        environ={"XDG_RUNTIME_DIR": str(peer.root / "runtime")},
        out=io.StringIO(),
        err=io.StringIO(),
        data=lambda _chunk: None,
    )


def invoke(peer, *arguments, host=None):
    made = host or host_of(peer)
    args = parser().parse_args(["device", *arguments])
    return device.run(args, made), made


def flash(peer, *extra, host=None):
    return invoke(
        peer,
        "flash",
        "--serial",
        SERIAL,
        *extra,
        str(peer.root / "image.uf2"),
        host=host,
    )


def test_token_refusal_is_not_an_empty_device_list(proxy):
    path = proxy.root / CONNECTION_FILE
    data = json.loads(path.read_text())
    data["token"] = secrets.token_hex(16)
    path.write_text(json.dumps(data))
    status, host = invoke(proxy, "list")
    assert status == 2
    assert "bad token" in host.err.getvalue()
    assert not host.out.getvalue()


def test_denied_serial_never_opens_or_loads(proxy):
    proxy.allowed = False
    status, host = flash(proxy)
    assert status == 2
    assert "not in the allow-list kept on the host" in host.err.getvalue()
    assert [r["cmd"] for r in proxy.requests] == ["list", "allowed"]


def test_outside_workspace_is_refused_before_load(proxy, tmp_path):
    image = tmp_path.parent / (tmp_path.name + "-outside.uf2")
    image.write_bytes(b"not in workspace")
    try:
        client = device.choose(host_of(proxy))
        with pytest.raises(RefusalError, match="outside") as refused:
            client.load(SERIAL, image)
        assert refused.value.status == CANNOT_TRY
        assert not any(r["cmd"] == "load" for r in proxy.requests)
    finally:
        image.unlink()


def test_host_path_refusal_is_preserved_even_for_a_forged_request(proxy):
    client = device.choose(host_of(proxy))
    with pytest.raises(RefusalError, match="not inside the workspace") as refused:
        client.call(cmd="load", serial=SERIAL, path="../outside.uf2")
    assert refused.value.status == 2


def test_flash_resets_waits_loads_and_reconnects(proxy):
    status, host = flash(proxy)
    assert status == 0, host.err.getvalue()
    assert [(r["baud"], r["port"]) for r in proxy.requests if r["cmd"] == "open"] == [
        (1200, "COM7"),
    ]
    load = next(r for r in proxy.requests if r["cmd"] == "load")
    assert load["path"] == "image.uf2"
    assert proxy.stage == "application"
    assert "has reconnected" in host.out.getvalue()
    cmds = [r["cmd"] for r in proxy.requests]
    assert cmds.index("open") < cmds.index("load") < len(cmds) - 1


@pytest.mark.parametrize("code", ["failed", "absent", "closed"])
def test_flash_continues_when_reset_open_vanishes(proxy, code):
    """AR-12: BOOTSEL enumeration proves the reset despite an open failure."""
    proxy.reset_error = code
    status, host = flash(proxy)
    assert status == 0, host.err.getvalue()
    assert "port vanished during the reset as expected" in host.out.getvalue()
    assert any(r["cmd"] == "load" for r in proxy.requests)
    assert proxy.stage == "application"
    assert "has reconnected" in host.out.getvalue()


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("failed", "reset open refused"),
        ("absent", "reset open refused"),
        ("closed", "closed the connection early"),
    ],
)
def test_reset_open_failure_without_bootloader_cannot_continue(
    proxy,
    monkeypatch,
    code,
    message,
):
    """AR-12: the open error and button instructions survive a BOOTSEL timeout."""
    proxy.reset_error = code
    proxy.reset = False
    monkeypatch.setattr(device, "BOOT_WAIT", 0.01)
    status, host = flash(proxy)
    assert status == 2
    assert message in host.err.getvalue()
    assert "did not appear in BOOTSEL" in host.err.getvalue()
    assert "hold BOOTSEL while plugging it in" in host.err.getvalue()
    assert "--no-touch" in host.err.getvalue()
    assert "as expected" not in host.out.getvalue()
    assert not any(r["cmd"] == "load" for r in proxy.requests)


@pytest.mark.parametrize(
    ("code", "expected"),
    [("denied", 2), ("busy", 1), ("token", 2), ("path", 2), ("request", 2)],
)
def test_reset_open_refusals_stop_without_waiting(proxy, code, expected):
    """AR-12: a refused reset must not wait for BOOTSEL or load an image."""
    proxy.reset_error = code
    status, host = flash(proxy)
    assert status == expected
    assert "reset open refused" in host.err.getvalue()
    assert proxy.requests[-1]["cmd"] == "open"
    assert not any(r["cmd"] == "load" for r in proxy.requests)


def test_flash_console_keeps_lock_until_match_and_logs(proxy):
    log = proxy.root / "console.log"
    status, host = flash(
        proxy,
        "--console",
        "--until",
        "boot: ready",
        "--timeout",
        "1",
        "--log",
        str(log),
    )
    assert status == 0, host.err.getvalue()
    assert log.read_bytes() == b"boot: ready\n"
    assert [r["baud"] for r in proxy.requests if r["cmd"] == "open"] == [1200, 115200]


def test_dry_run_does_not_reset_or_load(proxy):
    status, host = flash(proxy, "--dry-run")
    assert status == 0
    assert "would reset" in host.out.getvalue()
    assert not any(r["cmd"] in {"open", "load"} for r in proxy.requests)


def test_no_touch_uses_bootloader_but_never_opens_port(proxy):
    proxy.stage = "bootloader"
    status, host = flash(proxy, "--no-touch")
    assert status == 0, host.err.getvalue()
    assert not any(r["cmd"] == "open" for r in proxy.requests)


def test_no_touch_on_running_board_is_refused(proxy):
    status, host = flash(proxy, "--no-touch")
    assert status == 2
    assert "--no-touch needs it there" in host.err.getvalue()


@pytest.mark.parametrize(
    ("reset", "reconnect", "message"),
    [
        (False, True, "did not appear in BOOTSEL"),
        (True, False, "did not reconnect"),
    ],
)
def test_flash_timeouts_are_failures(proxy, monkeypatch, reset, reconnect, message):
    proxy.reset, proxy.reconnect = reset, reconnect
    monkeypatch.setattr(device, "BOOT_WAIT", 0.01)
    monkeypatch.setattr(device, "REBOOT_WAIT", 0.01)
    status, host = flash(proxy)
    assert status == 1
    assert message in host.err.getvalue()


def test_copy_failure_is_never_a_successful_flash(proxy):
    proxy.fail_load = True
    status, host = flash(proxy)
    assert status == 1
    assert "copy failed" in host.err.getvalue()


def test_console_timeout_is_one_and_log_keeps_partial_output(proxy):
    log = proxy.root / "output.log"
    status, host = invoke(
        proxy,
        "console",
        "--serial",
        SERIAL,
        "--until",
        "missing",
        "--timeout",
        ".03",
        "--log",
        str(log),
    )
    assert status == 1
    assert "no match" in host.err.getvalue()
    assert log.read_bytes() == b"boot: ready\n"


def test_console_matches_utf8_split_between_socket_reads(proxy):
    proxy.chunks = [b"\xc3", b"\xa9 ready"]
    status, host = invoke(
        proxy,
        "console",
        "--serial",
        SERIAL,
        "--until",
        "é ready",
        "--timeout",
        "1",
    )
    assert status == 0, host.err.getvalue()


@pytest.mark.parametrize(
    "options",
    [
        ["--until", "x"],
        ["--until", "[", "--timeout", "1"],
        ["--until", "x", "--timeout", "nan"],
        ["--until", "x", "--timeout", "0"],
    ],
)
def test_invalid_console_options_cannot_run(proxy, options):
    status, host = invoke(proxy, "console", "--serial", SERIAL, *options)
    assert status == 2
    assert "--" in host.err.getvalue()
    assert not any(r["cmd"] == "open" for r in proxy.requests)


def test_missing_proxy_prints_setup_instructions_without_network(tmp_path, monkeypatch):
    def unexpected_connection(*_args, **_kwargs):
        pytest.fail("missing proxy attempted network access")

    monkeypatch.setattr(socket, "create_connection", unexpected_connection)
    host = device.Host(cwd=tmp_path, out=io.StringIO(), err=io.StringIO())
    status = device.run(parser().parse_args(["device", "list"]), host)
    assert status == 2
    assert "setup-device-proxy.ps1 -Workspace" in host.err.getvalue()


def test_unreachable_proxy_prints_launcher_instructions(proxy):
    with socket.socket() as bound:
        bound.bind(("127.0.0.1", 0))
        data = {
            "host": "127.0.0.1",
            "port": bound.getsockname()[1],
            "token": proxy.token,
        }
        (proxy.root / CONNECTION_FILE).write_text(json.dumps(data))
        status, host = invoke(proxy, "list")
    assert status == 2
    assert "is not answering" in host.err.getvalue()
    assert "start-device-proxy.ps1" in host.err.getvalue()


@pytest.mark.parametrize("failure", [TimeoutError, ConnectionRefusedError])
def test_proxy_connect_failure_names_endpoint_and_launcher_once(
    tmp_path, monkeypatch, failure,
):
    """AR-15: stale connection files give one safe line, without retrying."""
    token = secrets.token_hex(16)
    (tmp_path / CONNECTION_FILE).write_text(json.dumps({
        "host": "192.0.2.1", "port": 47600, "token": token,
    }))
    attempts = []

    def connect(address, *, timeout):
        attempts.append((address, timeout))
        raise failure(token)

    monkeypatch.setattr(socket, "create_connection", connect)
    host = device.Host(cwd=tmp_path, out=io.StringIO(), err=io.StringIO())
    status = device.run(parser().parse_args(["device", "list"]), host)
    assert status == 2
    assert host.err.getvalue() == (
        "error: the device proxy is not answering at 192.0.2.1:47600; "
        "run the installed start-device-proxy.ps1 on Windows "
        "before using device commands\n"
    )
    assert token not in host.err.getvalue() + host.out.getvalue()
    assert attempts == [(("192.0.2.1", 47600), 10)]


def test_lock_contention_refuses_before_reset_and_releases_afterwards(proxy):
    host = host_of(proxy)
    with device.locked(SERIAL, host.environ):
        status, host = flash(proxy, host=host)
        assert status == 1
        assert "in use by process" in host.err.getvalue()
        with device.locked("OTHER", host.environ):
            pass
    assert not any(r["cmd"] == "open" for r in proxy.requests)
    status, host = flash(proxy)
    assert status == 0, host.err.getvalue()


def test_interactive_console_forwards_input_and_reconnects(proxy):
    proxy.chunks = [b"hello\n"]
    incoming, writer = socket.socketpair()
    writer.sendall(b"typed\n")
    seen = []
    host = dataclasses.replace(host_of(proxy), stdin=incoming.fileno())

    def output(chunk):
        seen.append(chunk)
        if len(seen) == 2:
            raise KeyboardInterrupt

    host.data = output
    try:
        status, host = invoke(proxy, "console", "--serial", SERIAL, host=host)
    finally:
        incoming.close()
        writer.close()
    assert status == 130
    assert b"typed\n" in proxy.typed
    assert len(seen) == 2
    assert "Lost connection" in host.err.getvalue()


@pytest.mark.parametrize("reply", [b"not json\n", b"[]\n", b'{"ok":42}\n', b""])
def test_malformed_or_closed_reply_is_not_success(proxy, reply):
    proxy.protocol_error = reply or b"\n"
    status, host = invoke(proxy, "list")
    assert status in {1, 2}
    assert "proxy" in host.err.getvalue()


def test_raw_byte_after_json_reply_is_not_consumed(proxy):
    client = device.choose(host_of(proxy))
    with contextlib.closing(client.open_serial(SERIAL, 115200, "COM7")) as connection:
        data = bytearray()
        while b"ready\n" not in data:
            data += connection.recv(4096)
    assert data == b"boot: ready\n"


def test_outside_image_is_refused_before_reset(proxy):
    image = proxy.root.parent / (proxy.root.name + "-outside.uf2")
    image.write_bytes(b"outside")
    try:
        status, host = invoke(proxy, "flash", "--serial", SERIAL, str(image))
        assert status == 2
        assert "outside" in host.err.getvalue()
        assert not any(r["cmd"] in {"open", "load"} for r in proxy.requests)
    finally:
        image.unlink()


def test_malformed_board_row_is_a_named_refusal(proxy):
    proxy.protocol_error = b'{"ok":true,"boards":[{}]}\n'
    status, host = invoke(proxy, "list")
    assert status == 2
    assert "invalid boards" in host.err.getvalue()


def test_named_port_waits_after_disconnect_until_agent_deadline(proxy):
    proxy.disconnect = True
    status, host = invoke(
        proxy,
        "console",
        "--serial",
        SERIAL,
        "--port",
        "COM7",
        "--until",
        "unseen",
        "--timeout",
        "2",
    )
    assert status == 1
    assert "no match" in host.err.getvalue()
    assert "Lost connection" in host.err.getvalue()


@pytest.mark.parametrize(("length", "expected"), [(65535, 0), (65536, 0), (65537, 1)])
def test_reply_line_limit_includes_the_delimiter(proxy, length, expected):
    body = b'{"ok":true,"boards":[]}'
    proxy.protocol_error = body + b" " * (length - len(body) - 1) + b"\n"
    status, host = invoke(proxy, "list")
    assert status == expected
    if expected:
        assert "proxy" in host.err.getvalue()


@pytest.mark.parametrize("address", ["127.0.0.1", "192.0.2.1"])
def test_connection_file_supplies_the_ipv4_address(tmp_path, address):
    """AR-15: the published listen address is the only client endpoint."""
    path = tmp_path / CONNECTION_FILE
    data = {"host": address, "port": 47600, "token": "fixture"}
    path.write_text(json.dumps(data))
    found, values = find_connection(tmp_path)
    assert found == path
    assert Proxy(device.Host(), found, values).address == (address, 47600)


@pytest.mark.parametrize(
    "address",
    [
        None,
        42,
        True,
        "",
        "example.invalid",
        "::1",
        "127.0.0.999",
        "127.00.0.1",
        str(ipaddress.IPv4Address(0)),
        "224.0.0.1",
        "255.255.255.255",
    ],
)
def test_invalid_connection_host_cannot_select_an_endpoint(tmp_path, address):
    """AR-15: malformed and wildcard endpoints are unavailable, not defaults."""
    data = {"host": address, "port": 47600, "token": "fixture"}
    (tmp_path / CONNECTION_FILE).write_text(json.dumps(data))
    assert find_connection(tmp_path) is None


def test_legacy_connection_without_host_requires_setup(tmp_path, monkeypatch):
    """AR-15: an old file never falls back to another network route."""
    (tmp_path / CONNECTION_FILE).write_text(
        json.dumps({"port": 47600, "token": "fixture"}),
    )

    def unexpected_connection(*_args, **_kwargs):
        pytest.fail("legacy connection file attempted network access")

    monkeypatch.setattr(socket, "create_connection", unexpected_connection)
    host = device.Host(cwd=tmp_path, out=io.StringIO(), err=io.StringIO())
    assert device.run(parser().parse_args(["device", "list"]), host) == 2
    assert "setup-device-proxy.ps1" in host.err.getvalue()


@pytest.mark.parametrize("relative", [".", "nested"])
def test_proxy_discovery_cannot_escape_the_test_directory(tmp_path, relative):
    """AR-15, EN-04.1: an ancestor connection must never select a real proxy."""
    decoy = tmp_path.parent / CONNECTION_FILE
    assert not decoy.exists()
    decoy.write_text(json.dumps({
        "host": "192.0.2.1", "port": 47600, "token": "ancestor-decoy",
    }))
    start = tmp_path / relative
    start.mkdir(exist_ok=True)
    try:
        assert find_connection(start) is None, "discovery escaped to the ancestor decoy"
    finally:
        decoy.unlink()
