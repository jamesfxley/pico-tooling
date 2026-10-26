# SPDX-License-Identifier: MIT
"""The proxy client: a program on the host that owns the boards (AR-15).

The host program listens on its configured IPv4 address and writes a connection
file, `.pico-device-proxy.json`, at the root of each workspace it serves. The
file holds the host, port and a token that names that workspace. A command finds it by
searching upward, then speaks newline-delimited JSON, one request per
connection:

    request  {"token": T, "cmd": "list"}
             {"token": T, "cmd": "allowed", "serial": S}
             {"token": T, "cmd": "open", "serial": S, "baud": B, "port": P}
             {"token": T, "cmd": "load", "serial": S, "path": "dir/image.uf2"}
    reply    {"ok": true, ...} or {"ok": false, "code": C, "error": "..."}

After the reply to `open`, the connection carries the port's bytes both ways
until either side closes it. The reply to `list` holds "boards": the fields of a
Board. `allowed` replies with "allowed". `load` names a path relative to the
workspace root; the program refuses an absolute path, `..` and anything outside.
Codes: token, denied, path, request, absent refuse before acting; busy and
failed report an attempt.
"""

import ipaddress
import json
import socket
from dataclasses import dataclass
from pathlib import Path

from .device_errors import CANNOT_TRY, FAILED, GoneError, RefusalError

CONNECTION_FILE = ".pico-device-proxy.json"
LINE_LIMIT = 65536
REFUSES = {"token", "denied", "path", "request", "absent"}


class UnreachableError(RefusalError):
    """Nothing answers at the address the connection file names."""

    def __init__(self, message):
        super().__init__(CANNOT_TRY, message)


def find_connection(start):
    """Return (file, data) for the nearest connection file above `start`, or None."""
    for directory in (Path(start).resolve(), *Path(start).resolve().parents):
        path = directory / CONNECTION_FILE
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, UnicodeError):
                return None
            valid = (
                isinstance(data, dict)
                and type(data.get("port")) is int
                and 0 < data["port"] < 65536
                and isinstance(data.get("token"), str)
                and bool(data["token"])
            )
            if not valid or not isinstance(data.get("host"), str):
                return None
            try:
                address = ipaddress.IPv4Address(data["host"])
            except ipaddress.AddressValueError:
                return None
            if (
                address.is_unspecified
                or address.is_multicast
                or address == ipaddress.IPv4Address("255.255.255.255")
            ):
                return None
            return path, data
    return None


def read_line(connection):
    """Read one line without taking a byte of the raw stream that may follow it."""
    line = bytearray()
    while not line.endswith(b"\n"):
        byte = connection.recv(1)
        if not byte:
            raise RefusalError(
                FAILED,
                "the device proxy closed the connection early",
                code="closed",
            )
        if len(line) >= LINE_LIMIT:
            raise RefusalError(FAILED, "the device proxy closed the connection early")
        line += byte
    return json.loads(line)


@dataclass(frozen=True)
class Board:
    serial: str
    product: str = ""
    ports: tuple = ()
    bootloader: bool = False
    drive: str | None = None
    listed: bool | None = None


class Proxy:
    """Boards on the host, reached through its device proxy."""

    def __init__(self, host, path, data):
        self.host = host
        self.root = path.parent
        self.address = (data["host"], data["port"])
        self.token = data["token"]
        self.deadline = None

    def request(self, **fields):
        """Send one request; return (reply, connection). A refusal raises."""
        timeout = 10
        if self.deadline is not None:
            timeout = min(timeout, self.deadline - self.host.clock())
            if timeout <= 0:
                raise RefusalError(
                    FAILED,
                    "no match: console timeout while waiting for proxy",
                )
        try:
            connection = socket.create_connection(self.address, timeout=timeout)
        except OSError as error:
            raise UnreachableError(
                f"the device proxy is not answering at "
                f"{self.address[0]}:{self.address[1]}; "
                "run the installed start-device-proxy.ps1 on Windows "
                "before using device commands",
            ) from error
        try:
            message = json.dumps({"token": self.token, **fields})
            connection.sendall(message.encode() + b"\n")
            reply = read_line(connection)
        except (OSError, ValueError, RefusalError) as error:
            connection.close()
            raise RefusalError(
                FAILED,
                f"the device proxy did not reply: {error}",
                code=(
                    "closed"
                    if isinstance(error, ConnectionError)
                    else getattr(error, "code", None)
                ),
            ) from error
        if not isinstance(reply, dict) or not isinstance(reply.get("ok"), bool):
            connection.close()
            raise RefusalError(CANNOT_TRY, "the device proxy sent an invalid reply")
        if not reply["ok"]:
            connection.close()
            code = reply.get("code")
            message = f"the device proxy refused: {reply.get('error', code)}"
            if code == "absent":
                raise GoneError(message)
            raise RefusalError(
                CANNOT_TRY if code in REFUSES else FAILED,
                message,
                code=code,
            )
        connection.settimeout(None)
        return reply, connection

    def call(self, **fields):
        reply, connection = self.request(**fields)
        connection.close()
        return reply

    def list(self):
        rows = self.call(cmd="list").get("boards")
        if not isinstance(rows, list) or not all(valid_board(row) for row in rows):
            raise RefusalError(CANNOT_TRY, "the device proxy sent invalid boards")
        return [
            Board(
                row["serial"],
                row.get("product", ""),
                tuple(row.get("ports", ())),
                bool(row.get("bootloader")),
                row.get("drive"),
                row.get("listed"),
            )
            for row in rows
        ]

    def allowed(self, serial):
        if self.call(cmd="allowed", serial=serial).get("allowed") is not True:
            raise RefusalError(
                CANNOT_TRY,
                f"{serial} is not in the allow-list kept on the host",
            )

    def open_serial(self, serial, baud, port):
        return self.request(cmd="open", serial=serial, baud=baud, port=port)[1]

    def image_path(self, image):
        try:
            relative = Path(image).resolve().relative_to(self.root)
        except ValueError as error:
            raise RefusalError(
                CANNOT_TRY,
                f"{image} is outside {self.root}, the workspace the proxy serves",
            ) from error
        if not Path(image).is_file():
            raise RefusalError(CANNOT_TRY, f"{image} is not an existing workspace file")
        return relative.as_posix()

    def load(self, serial, image):
        self.call(cmd="load", serial=serial, path=self.image_path(image))


def valid_board(row):
    return (
        isinstance(row, dict)
        and isinstance(row.get("serial"), str)
        and isinstance(row.get("ports", []), list)
        and all(isinstance(port, str) for port in row.get("ports", []))
        and isinstance(row.get("bootloader", False), bool)
        and row.get("listed") in (None, True, False)
    )
